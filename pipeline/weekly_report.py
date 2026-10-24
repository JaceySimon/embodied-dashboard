"""
生成每周简报（Markdown 格式）
可用于邮件、微信、Slack 推送
"""
import sys
import json
from pathlib import Path
from datetime import datetime, timedelta
from collections import Counter

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def generate_weekly_report():
    # 读取数据（优先读合并后的，包含工业界；否则找最新 arXiv backfill）
    from utils import find_latest_file
    combined_path = PROJECT_ROOT / "data" / "combined.json"
    latest_backfill = find_latest_file(PROJECT_ROOT / "data" / "backfill", "arxiv_backfill_*.json")

    if combined_path.exists():
        with open(combined_path, "r", encoding="utf-8") as f:
            papers = json.load(f)
    elif latest_backfill:
        with open(latest_backfill, "r", encoding="utf-8") as f:
            papers = json.load(f)
    else:
        print("错误：没有找到数据文件")
        return "# 周报生成失败：没有数据\n"

    # 本周论文
    week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    week_papers = [p for p in papers if p["published_at"] >= week_ago]

    # 标签统计
    tag_count = Counter()
    for p in week_papers:
        for t in p["tags"]:
            tag_count[t] += 1

    # 计算重要性分数
    weight_map = {
        "VLA": 10, "world_model": 8, "sim2real": 7,
        "diffusion_policy": 6, "foundation_model": 6,
        "manipulation": 4, "locomotion": 3,
    }
    for p in week_papers:
        score = sum(weight_map.get(t, 1) for t in p.get("tags", []))
        if p.get("has_real_robot", False):
            score += 5
        if p.get("is_open_source", False):
            score += 3
        score += min(len(p.get("authors", [])), 5)
        p["score"] = score

    top_papers = sorted(week_papers, key=lambda x: x["score"], reverse=True)[:10]

    # 工业界动态
    industry_papers = [p for p in week_papers if p.get("source_type") in ("company_blog", "lab_blog")]
    media_papers = [p for p in week_papers if p.get("source_type") == "media"]

    # 生成 Markdown
    today = datetime.now().strftime("%Y-%m-%d")
    md = f"""# 具身智能周报 · {today}

> 聚焦 VLA / 世界模型 / 仿真器，帮你少读 80% 垃圾

## 本周概况

- 本周新内容：**{len(week_papers)} 条**
- 学术论文：**{sum(1 for p in week_papers if p.get('source_type', 'arxiv') == 'arxiv')} 篇**
- 工业界博客：**{len(industry_papers)} 篇**
- 媒体报道：**{len(media_papers)} 篇**
- 真机实验：**{sum(1 for p in week_papers if p.get("has_real_robot", False))} 篇**
- 开源：**{sum(1 for p in week_papers if p.get("is_open_source", False))} 篇**

## 本周热门方向

"""
    for tag, count in tag_count.most_common(5):
        md += f"- {tag}: {count} 篇\n"

    # 工业界动态
    if industry_papers:
        md += "\n## 🏭 工业界动态\n\n"
        for p in industry_papers[:10]:
            md += f"- **{p.get('source_name', '')}**: [{p['title']}]({p['url']}) ({str(p['published_at'])[:10]})\n"

    md += "\n## 本周必看 10 篇\n\n"

    for i, p in enumerate(top_papers, 1):
        title = p["title"]
        authors = ", ".join(p["authors"][:3])
        if len(p["authors"]) > 3:
            authors += " et al."
        tags = ", ".join(p["tags"][:5])
        date = p["published_at"][:10]

        md += f"### {i}. {title}\n\n"
        md += f"- **作者**: {authors}\n"
        md += f"- **日期**: {date}\n"
        md += f"- **标签**: {tags}\n"
        if p.get("ai_summary"):
            md += f"- **摘要**: {p['ai_summary']}\n"
        md += f"- **链接**: {p['url']}\n\n"

    md += """---

## 关于本报告

这是由 [具身智能看板](https://github.com/yourusername/embodied-dashboard) 自动生成的周报。
聚焦三个方向：VLA / 世界模型 / 仿真器
"""

    return md


def main():
    report = generate_weekly_report()

    # 保存
    out_dir = PROJECT_ROOT / "output"
    out_dir.mkdir(exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    out_file = out_dir / f"weekly_{today}.md"

    with open(out_file, "w", encoding="utf-8") as f:
        f.write(report)

    print(f"周报已生成: {out_file}")
    print()
    print(report[:500])


if __name__ == "__main__":
    main()
