"""
合并 arXiv 论文 + RSS 工业界博客，生成统一的数据集
"""
import sys
import json
import yaml
from pathlib import Path
from datetime import datetime, timedelta

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from collectors.rss_collector import RSSCollector
from utils import logger


def collect_rss_papers(lookback_days: int = 90):
    """采集所有启用的 RSS 源"""
    with open(PROJECT_ROOT / "config" / "sources.yaml", "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    all_papers = []

    # 实验室博客
    for lab in config["l1"]["labs"]:
        if not lab.get("enabled", False) or not lab.get("rss"):
            continue

        try:
            collector = RSSCollector(
                source_name=lab["name"],
                rss_url=lab["rss"],
                source_level="L1",
                source_type="company_blog",
                keywords=lab.get("keywords", []),
                region=lab.get("region", "US"),
            )
            papers = collector.collect(lookback_days=lookback_days)
            all_papers.extend(papers)
            logger.info(f"[RSS] {lab['name']}: {len(papers)} 篇")
        except Exception as e:
            logger.warning(f"[RSS] {lab['name']} 失败: {e}")

    # L2 媒体
    for media in config["l2"]["media"]:
        if not media.get("enabled", False) or not media.get("rss"):
            continue

        try:
            collector = RSSCollector(
                source_name=media["name"],
                rss_url=media["rss"],
                source_level="L2",
                source_type="media",
                keywords=media.get("keywords", []),
                region=media.get("region", "US"),
            )
            papers = collector.collect(lookback_days=lookback_days)
            all_papers.extend(papers)
            logger.info(f"[RSS] {media['name']}: {len(papers)} 篇")
        except Exception as e:
            logger.warning(f"[RSS] {media['name']} 失败: {e}")

    return all_papers


def main():
    # 读取 arXiv 数据
    arxiv_path = PROJECT_ROOT / "data" / "backfill" / "arxiv_backfill_90d_20261022.json"
    with open(arxiv_path, "r", encoding="utf-8") as f:
        arxiv_papers = json.load(f)

    logger.info(f"arXiv 论文: {len(arxiv_papers)} 篇")

    # 采集 RSS
    rss_papers = collect_rss_papers(lookback_days=90)
    logger.info(f"RSS 博客: {len(rss_papers)} 篇")

    # 转换 RSS Paper 对象为 dict
    rss_dicts = []
    for p in rss_papers:
        d = {
            "id": p.id,
            "source_id": p.source_id,
            "source_level": str(p.source_level.value) if hasattr(p.source_level, "value") else "L1",
            "source_type": str(p.source_type.value) if hasattr(p.source_type, "value") else "company_blog",
            "source_name": p.source_name,
            "title": p.title,
            "abstract": p.abstract,
            "authors": p.authors,
            "url": p.url,
            "published_at": p.published_at.isoformat() if hasattr(p.published_at, "isoformat") else str(p.published_at),
            "tags": getattr(p, "tags", []),
            "code_url": getattr(p, "code_url", None),
        }
        rss_dicts.append(d)

    # 合并
    combined = arxiv_papers + rss_dicts

    # 按时间倒序
    combined.sort(key=lambda p: p.get("published_at", ""), reverse=True)

    # 保存
    out_path = PROJECT_ROOT / "data" / "combined.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(combined, f, ensure_ascii=False, indent=2, default=str)

    logger.info(f"合并完成: {len(combined)} 篇 -> {out_path}")

    # 统计来源
    sources = {}
    for p in combined:
        name = p.get("source_name", "unknown")
        sources[name] = sources.get(name, 0) + 1
    logger.info("来源分布:")
    for name, count in sorted(sources.items(), key=lambda x: -x[1]):
        logger.info(f"  {name}: {count}")


if __name__ == "__main__":
    main()
