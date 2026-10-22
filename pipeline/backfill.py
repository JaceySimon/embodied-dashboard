"""
历史数据爬取 - 简化版：直接采最近 N 天
用于冷启动：让首页不是空的
"""
import sys
import json
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from collectors.arxiv_collector import ArxivCollector
from pipeline.tagger import tag_papers
import yaml


def load_config():
    with open(PROJECT_ROOT / "config" / "sources.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def backfill(days: int = 30):
    """爬过去 N 天的数据"""
    config = load_config()
    arxiv_cfg = config["l0"]["arxiv"]

    print(f"开始爬历史数据：过去 {days} 天")
    print("=" * 60)

    collector = ArxivCollector(
        categories=arxiv_cfg["categories"],
        keywords=arxiv_cfg["keywords"],
        max_results=2000,
    )

    papers = collector.collect(lookback_days=days)

    # 打标
    papers = tag_papers(papers)

    # 保存
    out_dir = PROJECT_ROOT / "data" / "backfill"
    out_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    out_file = out_dir / f"arxiv_backfill_{days}d_{now.strftime('%Y%m%d')}.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump([p.model_dump() for p in papers], f, ensure_ascii=False, indent=2, default=str)

    print(f"\n保存到: {out_file}")
    print(f"总计: {len(papers)} 篇")

    # 统计
    from collections import Counter
    tag_count = Counter()
    for p in papers:
        for t in p.tags:
            tag_count[t] += 1
    print(f"\n热门标签:")
    for tag, cnt in tag_count.most_common(15):
        print(f"  {tag}: {cnt}")

    real_robot = sum(1 for p in papers if p.has_real_robot)
    open_source = sum(1 for p in papers if p.is_open_source)
    print(f"\n真机论文: {real_robot}/{len(papers)} = {real_robot/len(papers)*100:.1f}%")
    print(f"开源论文: {open_source}/{len(papers)} = {open_source/len(papers)*100:.1f}%")

    return papers


if __name__ == "__main__":
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    backfill(days=days)
