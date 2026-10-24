"""
arXiv 采集器 - 具身智能 / 机器人 / VLA 相关论文

v2 分层召回（解决旧版单一大查询命中 7 万条、max_results 截断只覆盖最近几天的问题）：
  A. cs.RO 机器人主分类 + 核心方向词（VLA / 世界模型 / 仿真 / 具身 / 操作）
  B. 其他分类（cs.AI/LG/CV/CL）仅保留强具身短语
  C. 重点公司 / 系统定向实体追踪（结果少而精准，避免技术报告论文被截断漏掉）
每个查询组按 submittedDate 倒序分页，拉到结果早于 lookback 窗口即停止；
跨组按 arXiv id 去重。关键词按 chunk 拆分为多个查询，避免 arXiv API 复杂查询返回 500。

带重试、缓存、错误处理。
"""
import arxiv
from datetime import datetime, timedelta
from typing import List, Optional
import re

from collectors.base import BaseCollector
from models.paper import Paper, SourceLevel, SourceType
from pipeline.clean import normalize_url, title_hash
from utils import retry, SimpleCache, logger


def _extract_url_from_comment(comment: Optional[str]) -> dict:
    """从 arXiv comment 里抽 project_page / code / dataset 链接"""
    result = {"project_page": None, "code": None, "dataset": None}
    if not comment:
        return result

    m = re.search(r"(?:code|github|repo)[^:]*:\s*(https?://[^\s;)]+)", comment, re.IGNORECASE)
    if m:
        result["code"] = m.group(1).rstrip(".,;")

    m = re.search(r"(?:project page|page|website|homepage)[^:]*:\s*(https?://[^\s;)]+)", comment, re.IGNORECASE)
    if m:
        result["project_page"] = m.group(1).rstrip(".,;")

    m = re.search(r"(?:dataset|data)[^:]*:\s*(https?://[^\s;)]+)", comment, re.IGNORECASE)
    if m:
        result["dataset"] = m.group(1).rstrip(".,;")

    return result


def _chunked(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def _term(expr: str) -> str:
    """构造 arXiv all: 检索项；含空格的短语加引号，单词不加。"""
    expr = expr.strip()
    if " " in expr:
        return f'all:"{expr}"'
    return f"all:{expr}"


class ArxivCollector(BaseCollector):
    """采集 arXiv 上具身智能 / 机器人 / VLA 相关论文（分层召回 + 分页）"""

    source_name = "arXiv"
    source_level = SourceLevel.L0
    source_type = SourceType.ARXIV

    def __init__(self, query_groups=None, categories=None, keywords=None,
                 page_size: int = 100, delay_seconds: float = 3.0,
                 max_per_query: int = 1500, keyword_chunk: int = 7,
                 max_results: int = 100):
        # 优先用 query_groups；否则退回旧的单一 categories+keywords（向后兼容）
        if query_groups:
            self.query_groups = query_groups
        else:
            self.query_groups = [{"name": "default",
                                  "categories": categories or ["cs.RO"],
                                  "keywords": keywords or []}]
        self.page_size = page_size
        self.delay_seconds = delay_seconds
        self.max_per_query = max_per_query
        self.keyword_chunk = keyword_chunk
        self.max_results = max_results  # 旧参数，仅向后兼容
        self.cache = SimpleCache(cache_dir="data/cache/arxiv", ttl_hours=6)

    @classmethod
    def from_config(cls, arxiv_cfg: dict) -> "ArxivCollector":
        groups = arxiv_cfg.get("query_groups")
        if not groups:
            return cls(
                categories=arxiv_cfg.get("categories", ["cs.RO"]),
                keywords=arxiv_cfg.get("keywords", []),
                max_results=arxiv_cfg.get("max_results_per_day", 100),
            )
        return cls(
            query_groups=groups,
            page_size=arxiv_cfg.get("page_size", 100),
            delay_seconds=arxiv_cfg.get("delay_seconds", 3.0),
            max_per_query=arxiv_cfg.get("max_per_query", 1500),
            keyword_chunk=arxiv_cfg.get("keyword_chunk", 7),
        )

    def _build_queries(self) -> List[tuple]:
        """把 query_groups 展开为 (group_name, query_string) 列表（自动拆 chunk）。"""
        queries: List[tuple] = []
        for g in self.query_groups:
            name = g.get("name", "g")
            cat_part = ""
            cats = g.get("categories")
            if cats:
                cat_part = "(" + " OR ".join(f"cat:{c}" for c in cats) + ")"
            elif g.get("restrict_robot_cat"):
                cat_part = "(cat:cs.RO OR cat:cs.AI OR cat:cs.LG OR cat:cs.CV OR cat:cs.CL)"

            # 实体追踪：每个实体是独立检索项，按 chunk 拼 OR
            terms = g.get("entities") or g.get("keywords") or []
            if not terms:
                if cat_part:
                    queries.append((name, cat_part))
                continue
            for j, chunk in enumerate(_chunked(terms, self.keyword_chunk)):
                body = "(" + " OR ".join(_term(t) for t in chunk) + ")"
                q = f"{cat_part} AND {body}" if cat_part else body
                queries.append((name if j == 0 else f"{name}_{j}", q))
        return queries

    @retry(max_retries=3, delay=2.0, backoff=2.0)
    def collect(self, lookback_days: int = 7) -> List[Paper]:
        """分层采集最近 N 天论文（带缓存、按窗口分页、跨组去重）。"""
        cache_key = f"arxiv_v2_{lookback_days}_{len(self.query_groups)}g"
        cached = self.cache.get(cache_key)
        if cached:
            logger.info(f"[arXiv] 命中缓存: {len(cached)} 篇")
            return [Paper(**p) if isinstance(p, dict) else p for p in cached]

        client = arxiv.Client(page_size=self.page_size,
                              delay_seconds=self.delay_seconds,
                              num_retries=3)
        cutoff = datetime.utcnow() - timedelta(days=lookback_days)
        seen_ids = set()
        results: List[Paper] = []

        for gname, query in self._build_queries():
            search = arxiv.Search(
                query=query,
                max_results=self.max_per_query,
                sort_by=arxiv.SortCriterion.SubmittedDate,
                sort_order=arxiv.SortOrder.Descending,
            )
            got = 0
            stopped_by_window = False
            try:
                for paper in client.results(search):
                    published = paper.published.replace(tzinfo=None)
                    if published < cutoff:
                        stopped_by_window = True
                        break  # 按时间倒序，后面都更早，安全停止本组
                    ax_id = paper.entry_id.split("/")[-1]
                    if ax_id in seen_ids:
                        continue
                    seen_ids.add(ax_id)
                    results.append(self._to_paper(paper, published))
                    got += 1
            except Exception as e:
                logger.error(f"[arXiv] 查询组 {gname} 失败: {e}")
                raise
            logger.info(f"[arXiv] 组 {gname:<16} 新增 {got:>4} 篇 "
                        f"{'(已覆盖窗口)' if stopped_by_window else '(达到单查询上限)'}")

        self.cache.set(cache_key, [p.to_dict() if hasattr(p, "to_dict") else p for p in results])
        logger.info(f"[arXiv] 分层采集合计 {len(results)} 篇（最近 {lookback_days} 天，去重后）")
        return results

    def _to_paper(self, paper, published) -> Paper:
        comment = paper.comment or ""
        extra_links = _extract_url_from_comment(comment)
        norm_url = normalize_url(paper.entry_id)
        norm_pdf = normalize_url(paper.pdf_url) if paper.pdf_url else None
        paper_id = f"arxiv:{paper.entry_id.split('/')[-1]}"

        return Paper(
            id=paper_id,
            source_id=paper_id,
            source_level=self.source_level,
            source_type=self.source_type,
            source_name=self.source_name,
            source_url="https://arxiv.org",
            title=paper.title.replace("\n", " ").strip(),
            abstract=paper.summary.replace("\n", " ").strip(),
            authors=[a.name for a in paper.authors],
            institutions=[],
            url=norm_url,
            pdf_url=norm_pdf,
            code_url=extra_links["code"],
            hf_url=None,
            published_at=published,
            updated_at=paper.updated.replace(tzinfo=None) if paper.updated else None,
            categories=[c.strip() for c in paper.categories],
            title_hash=title_hash(paper.title),
            raw_metadata={
                "comment": comment,
                "journal_ref": paper.journal_ref,
                "primary_category": paper.primary_category,
                "project_page": extra_links["project_page"],
                "dataset": extra_links["dataset"],
            },
        )


if __name__ == "__main__":
    import yaml
    from pathlib import Path
    cfg_path = Path(__file__).parent.parent / "config" / "sources.yaml"
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    collector = ArxivCollector.from_config(cfg["l0"]["arxiv"])
    print("查询组展开:")
    for n, q in collector._build_queries():
        print(f"  [{n}] {q[:110]}")
    papers = collector.collect(lookback_days=14)
    print(f"\n合计 {len(papers)} 篇")
    for p in papers[:8]:
        print(f"- {p.published_at.strftime('%Y-%m-%d')} {p.title[:78]}")
