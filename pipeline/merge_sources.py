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

from collectors.rss_collector import build_rss_collectors_from_config
from collectors.company_html_collector import build_html_collectors_from_config
from collectors.github_collector import build_github_collector_from_config
from collectors.huggingface_collector import build_hf_collector_from_config
from utils import logger


def collect_github_papers(config):
    """采集 GitHub 开源动态（仓库 + 框架发布）"""
    collector = build_github_collector_from_config(config)
    if not collector:
        return []
    try:
        return collector.collect()
    except Exception as e:
        logger.warning(f"[GitHub] 采集失败: {e}")
        return []


def collect_hf_papers(config):
    """采集 Hugging Face 模型权重发布"""
    collector = build_hf_collector_from_config(config)
    if not collector:
        return []
    try:
        return collector.collect()
    except Exception as e:
        logger.warning(f"[HuggingFace] 采集失败: {e}")
        return []


def collect_rss_papers(lookback_days: int = 90):
    """采集所有启用的 RSS 源（实验室博客 + 公司博客 + 媒体）"""
    with open(PROJECT_ROOT / "config" / "sources.yaml", "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    all_papers = []
    collectors = build_rss_collectors_from_config(config)
    logger.info(f"[RSS] 共 {len(collectors)} 个启用的 RSS 源")

    for collector in collectors:
        try:
            papers = collector.collect(lookback_days=lookback_days)
            all_papers.extend(papers)
            logger.info(f"[RSS] {collector.source_name}: {len(papers)} 篇")
        except Exception as e:
            logger.warning(f"[RSS] {collector.source_name} 失败: {e}")

    # 无 RSS 的公司网站，走 HTML 采集器
    # 公司产品/技术发布更新频率低、生命周期长，用 180 天窗口（比论文的 90 天宽）
    html_collectors = build_html_collectors_from_config(config)
    logger.info(f"[HTML] 共 {len(html_collectors)} 个 HTML 公司源")
    for collector in html_collectors:
        try:
            papers = collector.collect(lookback_days=180)
            all_papers.extend(papers)
        except Exception as e:
            logger.warning(f"[HTML] {collector.source_name} 失败: {e}")

    return all_papers


def main():
    # 读取最新 arXiv backfill
    from utils import find_latest_file
    arxiv_path = find_latest_file(PROJECT_ROOT / "data" / "backfill", "arxiv_backfill_*.json")
    if not arxiv_path:
        logger.error("没有找到 arXiv backfill 文件，请先跑 python pipeline/backfill.py 90")
        return
    with open(arxiv_path, "r", encoding="utf-8") as f:
        arxiv_papers = json.load(f)

    logger.info(f"arXiv 论文: {len(arxiv_papers)} 篇")

    with open(PROJECT_ROOT / "config" / "sources.yaml", "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    # 采集 RSS（内部会再读一次配置，保持原签名）
    rss_papers = collect_rss_papers(lookback_days=90)
    logger.info(f"RSS 博客: {len(rss_papers)} 篇")

    # 采集 GitHub 开源动态
    github_papers = collect_github_papers(config)
    logger.info(f"GitHub 开源: {len(github_papers)} 条")

    # 采集 Hugging Face 模型发布
    hf_papers = collect_hf_papers(config)
    logger.info(f"HuggingFace 模型: {len(hf_papers)} 个")

    # 转换 RSS Paper 对象为 dict
    def enum_val(v, default):
        if hasattr(v, "value"):
            return v.value
        return str(v) if v else default

    def paper_to_dict(p):
        return {
            "id": p.id,
            "source_id": p.source_id,
            "source_level": enum_val(p.source_level, "L1"),
            "source_type": enum_val(p.source_type, "company_blog"),
            "source_name": p.source_name,
            "title": p.title,
            "abstract": p.abstract,
            "authors": p.authors,
            "url": p.url,
            "published_at": p.published_at.isoformat() if hasattr(p.published_at, "isoformat") else str(p.published_at),
            "tags": getattr(p, "tags", []),
            "code_url": getattr(p, "code_url", None),
            "is_open_source": getattr(p, "is_open_source", None),
            "raw_metadata": getattr(p, "raw_metadata", None),
        }

    rss_dicts = [paper_to_dict(p) for p in rss_papers]
    github_dicts = [paper_to_dict(p) for p in github_papers]
    hf_dicts = [paper_to_dict(p) for p in hf_papers]

    # 合并
    combined = arxiv_papers + rss_dicts + github_dicts + hf_dicts

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
