"""
批量生成 AI 摘要
给本周必看的论文生成 3 句话摘要
"""
import sys
import json
import time
from pathlib import Path
from datetime import datetime, timedelta

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.llm_tagger import generate_summary, LLMTagger
from models.paper import Paper


def main():
    from utils import find_latest_file
    # 命令行参数：生成篇数
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 20

    # 优先读合并数据，否则最新 arXiv backfill
    combined_path = PROJECT_ROOT / "data" / "combined.json"
    latest_backfill = find_latest_file(PROJECT_ROOT / "data" / "backfill", "arxiv_backfill_*.json")
    if combined_path.exists():
        data_path = combined_path
    elif latest_backfill:
        data_path = latest_backfill
    else:
        print("错误：没有找到数据文件")
        return

    with open(data_path, "r", encoding="utf-8") as f:
        papers_data = json.load(f)

    # 只处理本周论文
    week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    week_papers = [p for p in papers_data if p.get("published_at", "")[:10] >= week_ago]

    # 重要性评分（与看板"本周必看"一致），优先给最重要的论文生成摘要
    weight_map = {
        "VLA": 10, "world_model": 8, "sim2real": 7,
        "diffusion_policy": 6, "foundation_model": 6,
        "manipulation": 4, "locomotion": 3,
    }

    def score(p):
        s = sum(weight_map.get(t, 1) for t in p.get("tags", []))
        if p.get("has_real_robot"):
            s += 5
        if p.get("is_open_source"):
            s += 3
        if p.get("code_url"):
            s += 4
        s += min(len(p.get("authors", [])), 5)
        return s

    # 只给学术论文（有摘要可总结）生成，工业界博客自带摘要
    candidates = [p for p in week_papers if not p.get("ai_summary") and p.get("abstract")]
    candidates.sort(key=score, reverse=True)

    print(f"本周论文: {len(week_papers)} 篇，待生成摘要候选: {len(candidates)} 篇")
    print(f"给重要性 Top {n} 生成摘要（节省 API 费用）")
    print()

    # 初始化 LLM
    llm = LLMTagger(provider="deepseek")
    if not llm.api_key:
        print("错误：未设置 LLM_API_KEY（请在 .env 中配置 DeepSeek key）")
        return

    # 生成摘要
    target = candidates[:n]
    success = 0
    for i, p in enumerate(target):
        print(f"[{i+1}/{len(target)}] {p['title'][:55]}...")

        paper = Paper(**p)
        try:
            summary = generate_summary(paper, llm)
            if summary:
                p["ai_summary"] = summary
                success += 1
                print(f"  ✓")
            else:
                print(f"  ✗ 失败")
        except Exception as e:
            print(f"  ✗ 错误: {e}")

        time.sleep(0.8)  # 避免请求过快

    # 保存
    with open(data_path, "w", encoding="utf-8") as f:
        json.dump(papers_data, f, ensure_ascii=False, indent=2, default=str)

    print()
    print(f"完成！成功 {success}/{len(target)}，摘要已保存到 {data_path.name}")


if __name__ == "__main__":
    main()
