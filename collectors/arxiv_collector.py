"""
arXiv 采集器 - 具身智能相关论文
"""
import arxiv
from datetime import datetime, timedelta, timezone
from typing import List, Optional
import re
import hashlib
from urllib.parse import urlparse

from collectors.base import BaseCollector
from models.paper import Paper, SourceLevel, SourceType
from pipeline.clean import normalize_url, normalize_title, title_hash


def _extract_url_from_comment(comment: Optional[str]) -> dict:
    """从 arXiv comment 里抽 project_page / code / dataset 链接"""
    result = {"project_page": None, "code": None, "dataset": None}
    if not comment:
        return result

    # 匹配 Code: https://... 或 Code is at https://...
    m = re.search(r"(?:code|github|repo)[^:]*:\s*(https?://[^\s;)]+)", comment, re.IGNORECASE)
    if m:
        result["code"] = m.group(1).rstrip(".,;")

    # Project page
    m = re.search(r"(?:project page|page|website|homepage)[^:]*:\s*(https?://[^\s;)]+)", comment, re.IGNORECASE)
    if m:
        result["project_page"] = m.group(1).rstrip(".,;")

    # Dataset
    m = re.search(r"(?:dataset|data)[^:]*:\s*(https?://[^\s;)]+)", comment, re.IGNORECASE)
    if m:
        result["dataset"] = m.group(1).rstrip(".,;")

    return result


def _extract_institutions_from_abstract(abstract: str) -> List[str]:
    """v1 简化：从摘要里抽常见机构关键词（v2 用 LLM 抽）"""
    # 这个先留空，v2 用 LLM 抽
    return []


class ArxivCollector(BaseCollector):
    """采集 arXiv 上具身智能/机器人相关论文"""

    source_name = "arXiv"
    source_level = SourceLevel.L0
    source_type = SourceType.ARXIV

    def __init__(self, categories: List[str], keywords: List[str], max_results: int = 100):
        self.categories = categories
        self.keywords = keywords
        self.max_results = max_results

    def _build_query(self) -> str:
        """构建 arXiv 查询字符串"""
        # 分类条件
        cat_conditions = " OR ".join([f"cat:{c}" for c in self.categories])
        # 关键词条件（标题或摘要包含任一）
        kw_conditions = " OR ".join([f"all:\"{kw}\"" for kw in self.keywords])
        # 组合：(cat in cs.RO etc) AND (keywords match)
        query = f"({cat_conditions}) AND ({kw_conditions})"
        return query

    def collect(self, lookback_days: int = 7) -> List[Paper]:
        """采集最近 N 天的论文"""
        query = self._build_query()
        print(f"[arXiv] 查询: {query[:100]}...")

        client = arxiv.Client(
            page_size=50,
            delay_seconds=3.0,  # 礼貌访问，3 秒一次
            num_retries=3,
        )

        search = arxiv.Search(
            query=query,
            max_results=self.max_results,
            sort_by=arxiv.SortCriterion.SubmittedDate,
            sort_order=arxiv.SortOrder.Descending,
        )

        results = []
        cutoff = datetime.utcnow() - timedelta(days=lookback_days)

        try:
            for paper in client.results(search):
                # 过滤时间
                published = paper.published.replace(tzinfo=None)
                if published < cutoff:
                    continue

                # 从 comment 抽链接
                comment = paper.comment or ""
                extra_links = _extract_url_from_comment(comment)

                # 规范化 URL
                norm_url = normalize_url(paper.entry_id)
                norm_pdf = normalize_url(paper.pdf_url) if paper.pdf_url else None

                # 生成 id
                paper_id = f"arxiv:{paper.entry_id.split('/')[-1]}"

                # 转换为 Paper 模型
                p = Paper(
                    id=paper_id,
                    source_id=paper_id,
                    source_level=self.source_level,
                    source_type=self.source_type,
                    source_name=self.source_name,
                    source_url="https://arxiv.org",
                    title=paper.title.replace("\n", " ").strip(),
                    abstract=paper.summary.replace("\n", " ").strip(),
                    authors=[a.name for a in paper.authors],
                    institutions=_extract_institutions_from_abstract(paper.summary),
                    url=norm_url,
                    pdf_url=norm_pdf,
                    code_url=extra_links["code"],
                    hf_url=None,  # v2 从 HuggingFace 关联
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
                results.append(p)

        except Exception as e:
            print(f"[arXiv] 采集失败: {e}")

        print(f"[arXiv] 采集到 {len(results)} 篇论文（最近 {lookback_days} 天）")
        return results


if __name__ == "__main__":
    # 测试
    collector = ArxivCollector(
        categories=["cs.RO"],
        keywords=["robot", "manipulation", "embodied", "VLA"],
        max_results=20,
    )
    papers = collector.collect(lookback_days=3)
    for p in papers[:5]:
        print(f"- {p.title[:80]}...")
        print(f"  {p.published_at.strftime('%Y-%m-%d')} | {', '.join(p.authors[:3])}")
