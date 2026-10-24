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
    # 读取数据
    data_path = PROJECT_ROOT / "data" / "backfill" / "arxiv_backfill_90d_20261022.json"
    with open(data_path, "r", encoding="utf-8") as f:
        papers_data = json.load(f)

    # 只处理本周论文
    week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    week_papers = [p for p in papers_data if p["published_at"] >= week_ago]

    print(f"本周论文: {len(week_papers)} 篇")
    print(f"只给前 20 篇生成摘要（节省 API 费用）")
    print()

    # 初始化 LLM
    llm = LLMTagger(provider="deepseek")
    if not llm.api_key:
        print("错误：未设置 LLM_API_KEY")
        return

    # 生成摘要
    target = week_papers[:20]
    for i, p in enumerate(target):
        if p.get("ai_summary"):
            print(f"[{i+1}/{len(target)}] 已有摘要，跳过: {p['title'][:50]}")
            continue

        print(f"[{i+1}/{len(target)}] 生成摘要: {p['title'][:50]}...")

        paper = Paper(**p)
        try:
            summary = generate_summary(paper, llm)
            if summary:
                p["ai_summary"] = summary
                print(f"  ✓ 成功")
            else:
                print(f"  ✗ 失败")
        except Exception as e:
            print(f"  ✗ 错误: {e}")

        time.sleep(1)  # 避免请求过快

    # 保存
    with open(data_path, "w", encoding="utf-8") as f:
        json.dump(papers_data, f, ensure_ascii=False, indent=2, default=str)

    print()
    print(f"完成！摘要已保存到 {data_path}")


if __name__ == "__main__":
    main()
