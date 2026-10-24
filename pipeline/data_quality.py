"""
数据质量抽检
验证标签、排序、垃圾数据、来源分布
"""
import json
import sys
from pathlib import Path
from collections import Counter
from datetime import datetime, timedelta

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
from utils import find_latest_file


def main():
    combined_path = PROJECT_ROOT / "data" / "combined.json"
    if combined_path.exists():
        papers = json.load(open(combined_path, encoding="utf-8"))
    else:
        path = find_latest_file(PROJECT_ROOT / "data" / "backfill", "arxiv_backfill_*.json")
        papers = json.load(open(path, encoding="utf-8"))

    print("=" * 70)
    print("数据质量报告")
    print("=" * 70)

    # 1. 总量
    print(f"\n总条目: {len(papers)}")

    # 2. 来源类型分布
    print("\n【来源类型】")
    for k, v in Counter(p.get("source_type", "unknown") for p in papers).most_common():
        print(f"  {k}: {v}")

    # 3. 日期范围
    dates = [p.get("published_at", "")[:10] for p in papers if p.get("published_at")]
    if dates:
        print(f"\n【日期范围】{min(dates)} ~ {max(dates)}")

    # 本周
    week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    week_papers = [p for p in papers if p.get("published_at", "")[:10] >= week_ago]
    print(f"本周条目: {len(week_papers)}")

    # 4. 字段完整性
    print("\n【字段完整性】")
    no_title = sum(1 for p in papers if not p.get("title"))
    no_abstract = sum(1 for p in papers if not p.get("abstract"))
    no_url = sum(1 for p in papers if not p.get("url"))
    print(f"  缺标题: {no_title}")
    print(f"  缺摘要: {no_abstract}")
    print(f"  缺链接: {no_url}")

    # 5. 重复检测（同 URL）
    urls = [p.get("url") for p in papers if p.get("url")]
    dup_urls = {u: c for u, c in Counter(urls).items() if c > 1}
    print(f"\n【重复 URL】{len(dup_urls)} 个")

    # 6. 标签分布
    print("\n【标签分布 Top 15】")
    tag_c = Counter()
    for p in papers:
        for t in p.get("tags", []):
            tag_c[t] += 1
    for k, v in tag_c.most_common(15):
        print(f"  {k}: {v}")

    # 7. 抽检本周必看（按论文现有的简单分数）
    weight_map = {
        "VLA": 10, "world_model": 8, "sim2real": 7,
        "diffusion_policy": 6, "foundation_model": 6,
    }
    for p in week_papers:
        score = sum(weight_map.get(t, 1) for t in p.get("tags", []))
        if p.get("has_real_robot"):
            score += 5
        if p.get("is_open_source"):
            score += 3
        score += min(len(p.get("authors", [])), 5)
        p["_score"] = score

    print("\n【本周必看 Top 10（抽检排序质量）】")
    top = sorted(week_papers, key=lambda x: x["_score"], reverse=True)[:10]
    for i, p in enumerate(top, 1):
        title = p["title"][:60]
        tags = ",".join(p.get("tags", [])[:4])
        print(f"  {i}. [{p['_score']:2d}] {title}")
        print(f"       {tags}")

    # 8. 异常：标题过短或含乱码
    print("\n【疑似异常标题】")
    weird = [p for p in papers if len(p.get("title", "")) < 15 or "\\u" in p.get("title", "")]
    print(f"  共 {len(weird)} 条（标题过短或含转义残留）")
    for p in weird[:3]:
        print(f"  - {p.get('title', '')[:70]}")

    # 9. 工业界内容抽查
    print("\n【工业界/媒体内容抽查】")
    non_arxiv = [p for p in papers if p.get("source_type") != "arxiv"]
    print(f"  共 {len(non_arxiv)} 条")
    for p in non_arxiv[:8]:
        print(f"  - [{p.get('source_name')}] {p['title'][:55]}")


if __name__ == "__main__":
    main()
