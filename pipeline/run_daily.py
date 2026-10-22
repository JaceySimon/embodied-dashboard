"""
具身智能看板 - 主 pipeline v2
采集 → 清洗 → 去重 → 打标 → 事件聚合 → 保存
"""
import os
import sys
import json
import yaml
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from collectors.arxiv_collector import ArxivCollector
from collectors.rss_collector import RSSCollector, build_rss_collectors_from_config
from collectors.x_collector import XCollector
from collectors.x_api_collector import build_x_collector_from_config
from pipeline.clean import deduplicate_papers
from pipeline.aggregate import EventAggregator
from pipeline.tagger import tag_papers
from pipeline.llm_tagger import build_llm_tagger_from_config


def load_config(config_path: str) -> dict:
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def run_daily(config_path: str = None, lookback_days: int = 7):
    """跑每日 pipeline"""
    if config_path is None:
        config_path = PROJECT_ROOT / "config" / "sources.yaml"

    now = datetime.now(timezone.utc)
    print("=" * 60)
    print(f"具身智能看板 pipeline 启动 - {now.isoformat()}")
    print("=" * 60)

    config = load_config(config_path)
    all_papers = []

    # ========== 1. arXiv 采集 ==========
    print(f"\n[1/5] 采集 arXiv...")
    arxiv_cfg = config["l0"]["arxiv"]
    arxiv_collector = ArxivCollector(
        categories=arxiv_cfg["categories"],
        keywords=arxiv_cfg["keywords"],
        max_results=arxiv_cfg["max_results_per_day"],
    )
    arxiv_papers = arxiv_collector.collect(lookback_days=lookback_days)
    all_papers.extend(arxiv_papers)

    # ========== 2. RSS 采集 ==========
    print(f"\n[2/5] 采集 RSS 源（实验室/公司博客/媒体）...")
    rss_collectors = build_rss_collectors_from_config(config)
    print(f"  共 {len(rss_collectors)} 个 RSS 源")
    rss_papers = []
    for collector in rss_collectors:
        rss_papers.extend(collector.collect(lookback_days=lookback_days))
    all_papers.extend(rss_papers)
    print(f"  RSS 总计: {len(rss_papers)} 篇")

    # ========== 3. X 采集 ==========
    print(f"\n[3/5] 采集 X 白名单账号...")
    x_api_collector = build_x_collector_from_config(config)
    if x_api_collector:
        x_papers = x_api_collector.collect(lookback_days=lookback_days)
        all_papers.extend(x_papers)
        print(f"  X API 总计: {len(x_papers)} 条")
    else:
        print("  X 采集未启用（需要 X_BEARER_TOKEN 环境变量）")

    # ========== 4. 打标 ==========
    print(f"\n[4/5] 打标...")
    all_papers = tag_papers(all_papers)  # 规则打标（兜底）
    llm_tagger = build_llm_tagger_from_config(config)
    if llm_tagger:
        all_papers = llm_tagger.tag_papers(all_papers)  # LLM 打标（可选）

    # ========== 5. 事件聚合 ==========
    print(f"\n[5/5] 事件聚合... 共 {len(all_papers)} 篇原始")
    aggregator = EventAggregator(
        similarity_threshold=config["global"]["aggregation"].get("similarity_threshold", 0.6)
    )
    events = aggregator.aggregate(all_papers)
    print(f"  聚合后事件: {len(events)} 个")
    print(f"  聚合统计:")
    print(f"    arXiv 版本合并: {aggregator.stats['arxiv_version_merged']} 篇")
    print(f"    RSS 关联到 arXiv: {aggregator.stats['arxiv_linked_attached']} 篇")
    print(f"    URL 精确匹配: {aggregator.stats['url_matched']} 篇")
    print(f"    标题相似度匹配: {aggregator.stats['title_matched']} 篇")
    print(f"    独立 L1/L2 事件: {aggregator.stats['independent_l1_l2']} 个")

    # ========== 保存 ==========
    print(f"\n保存结果...")
    ts = now.strftime("%Y%m%d_%H%M%S")

    # 原始
    raw_dir = PROJECT_ROOT / "data" / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_file = raw_dir / f"papers_{ts}.json"
    with open(raw_file, "w", encoding="utf-8") as f:
        json.dump([p.model_dump() for p in all_papers], f, ensure_ascii=False, indent=2, default=str)
    print(f"  原始: {raw_file.name}")

    # 事件
    processed_dir = PROJECT_ROOT / "data" / "processed"
    processed_dir.mkdir(parents=True, exist_ok=True)
    event_file = processed_dir / f"events_{ts}.json"
    with open(event_file, "w", encoding="utf-8") as f:
        json.dump([e.model_dump() for e in events], f, ensure_ascii=False, indent=2, default=str)
    print(f"  事件: {event_file.name}")

    # 摘要
    print("\n" + "=" * 60)
    print("采集摘要")
    print("=" * 60)
    print(f"时间范围: 最近 {lookback_days} 天")
    print(f"原始论文/帖子: {len(all_papers)}")
    print(f"聚合后事件: {len(events)}")

    # 按来源统计
    by_source = {}
    for p in all_papers:
        by_source[p.source_name] = by_source.get(p.source_name, 0) + 1
    print(f"\n按来源:")
    for src, cnt in sorted(by_source.items(), key=lambda x: -x[1])[:10]:
        print(f"  {src}: {cnt}")

    # 按标签统计
    tag_count = {}
    for p in all_papers:
        for t in p.tags:
            tag_count[t] = tag_count.get(t, 0) + 1
    print(f"\n热门标签:")
    for tag, cnt in sorted(tag_count.items(), key=lambda x: -x[1])[:10]:
        print(f"  {tag}: {cnt}")

    # 展示前 10 个事件
    print(f"\n前 10 个事件（按分数排序）:")
    for i, e in enumerate(events[:10], 1):
        p = e.primary_paper
        ext_count = len(e.extensions)
        tags_str = ",".join(p.tags[:5]) if p.tags else ""
        print(f"  {i}. [{e.score:.2f}] {p.title[:65]}")
        print(f"     {p.source_name} | {p.published_at.strftime('%m-%d')} | 延伸{ext_count}个 | {tags_str}")

    return events


if __name__ == "__main__":
    run_daily(lookback_days=7)
