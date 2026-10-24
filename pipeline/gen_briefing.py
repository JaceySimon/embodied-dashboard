"""
AI 方向综述（Research Briefing）
为核心方向检索近期重要论文，用 DeepSeek 生成结构化、带引用的方向综述。
输出 data/briefing.json，供 generate_html.py 展示。

设计原则：
- 综述必须引用真实论文 id（从检索结果中引用），避免幻觉
- 预生成、静态，符合静态站点架构
- 成本极低（每个方向 1 次调用）
"""
import sys
import json
import time
from pathlib import Path
from datetime import datetime, timedelta

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.llm_tagger import LLMTagger

# 四个核心方向：标签集合 + 标题强词
DIRECTIONS = [
    {
        "key": "vla",
        "name": "VLA 视觉-语言-动作模型",
        "tags": {"VLA", "foundation_model"},
        "title_terms": ["vision-language-action", "vision language action", "robot foundation model"],
    },
    {
        "key": "world_model",
        "name": "世界模型 / World-Action Model",
        "tags": {"world_model"},
        "title_terms": ["world model", "world action model", "world-action", "video prediction"],
    },
    {
        "key": "sim2real",
        "name": "仿真与 Sim-to-Real",
        "tags": {"sim2real"},
        "title_terms": ["sim-to-real", "sim2real", "simulator", "simulation"],
    },
    {
        "key": "policy",
        "name": "模仿学习与策略学习",
        "tags": {"imitation_learning", "diffusion_policy", "reinforcement_learning"},
        "title_terms": ["imitation", "diffusion policy", "flow matching", "policy learning"],
    },
]

WINDOW_DAYS = 90
TOP_N = 15

WEIGHT_MAP = {
    "VLA": 10, "world_model": 8, "sim2real": 7, "diffusion_policy": 6,
    "foundation_model": 6, "manipulation": 4, "locomotion": 3, "navigation": 3,
}


def score(p):
    s = sum(WEIGHT_MAP.get(t, 1) for t in p.get("tags", []))
    if "real_robot" in p.get("tags", []):
        s += 5
    if "open_source" in p.get("tags", []):
        s += 3
    if p.get("code_url"):
        s += 4
    s += min(len(p.get("authors", [])), 5)
    return s


def match_direction(p, direction):
    tags = set(p.get("tags", []))
    if tags & direction["tags"]:
        return True
    title = (p.get("title") or "").lower()
    return any(term in title for term in direction["title_terms"])


BRIEFING_PROMPT = """你是具身智能 / 机器人领域的资深研究员。下面是「{direction}」方向近 {days} 天的部分重要论文。

请只基于这些论文，写一份结构化的中文方向综述。

论文列表（格式：[id] 日期 | 标题 | 摘要）：
{paper_list}

请严格输出 JSON（不要任何额外文字、不要 markdown 代码块），结构如下：
{{
  "overview": "2-3 句话，概述该方向近期在解决的核心问题与整体进展",
  "lines": [
    {{
      "name": "技术路线 / 主题名称",
      "paper_ids": ["从上面列表中选取的真实 id", "..."],
      "point": "1-2 句话，该路线的核心思路与进展"
    }}
  ],
  "trends": ["1-2 条值得关注的趋势或判断"]
}}

硬性要求：
1. paper_ids 必须逐字来自上面论文列表的 id，禁止编造或改写；
2. 只总结给定论文覆盖的内容，不要引入列表之外的信息；
3. lines 给出 3-5 条主要技术路线；trends 给出 2-3 条；
4. 表述专业、具体，避免空泛的套话。
"""


def build_paper_list(papers):
    lines = []
    for p in papers:
        pid = p["id"]
        date = str(p.get("published_at", ""))[:10]
        title = p.get("title", "")
        abstract = (p.get("abstract", "") or "")[:180]
        lines.append(f"[{pid}] {date} | {title} | {abstract}")
    return "\n".join(lines)


def parse_json_lenient(text):
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    # 截取首个 { 到最后一个 }
    lo, hi = text.find("{"), text.rfind("}")
    if lo != -1 and hi != -1:
        text = text[lo:hi + 1]
    return json.loads(text)


def main():
    combined_path = PROJECT_ROOT / "data" / "combined.json"
    if not combined_path.exists():
        print("错误：未找到 data/combined.json")
        return
    papers = json.load(open(combined_path, encoding="utf-8"))

    cutoff = (datetime.now() - timedelta(days=WINDOW_DAYS)).strftime("%Y-%m-%d")
    recent = [p for p in papers if p.get("published_at", "")[:10] >= cutoff]

    llm = LLMTagger(provider="deepseek")
    if not llm.api_key:
        print("错误：未设置 LLM_API_KEY")
        return

    briefings = []
    for direction in DIRECTIONS:
        matched = [p for p in recent if match_direction(p, direction)]
        matched.sort(key=score, reverse=True)
        top = matched[:TOP_N]
        print(f"[{direction['key']}] 匹配 {len(matched)}，取 Top {len(top)}")

        paper_list = build_paper_list(top)
        prompt = BRIEFING_PROMPT.format(
            direction=direction["name"], days=WINDOW_DAYS, paper_list=paper_list)

        result = None
        for attempt in range(2):
            resp = llm._call_llm(prompt)
            if resp:
                try:
                    result = parse_json_lenient(resp)
                    break
                except Exception as e:
                    print(f"  解析失败(尝试{attempt+1}): {e}")
            time.sleep(2)

        if result:
            # 校验 paper_ids 真实存在
            valid_ids = {p["id"] for p in top}
            for line in result.get("lines", []):
                line["paper_ids"] = [pid for pid in line.get("paper_ids", []) if pid in valid_ids]
            briefings.append({
                "key": direction["key"],
                "name": direction["name"],
                "overview": result.get("overview", ""),
                "lines": result.get("lines", []),
                "trends": result.get("trends", []),
            })
            print("  OK")
        else:
            print("  失败，跳过")
        time.sleep(1)

    out_path = PROJECT_ROOT / "data" / "briefing.json"
    json.dump({"generated_at": datetime.now().isoformat(),
               "window_days": WINDOW_DAYS,
               "briefings": briefings},
              open(out_path, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print(f"\n生成: {out_path}（{len(briefings)} 个方向）")


if __name__ == "__main__":
    main()
