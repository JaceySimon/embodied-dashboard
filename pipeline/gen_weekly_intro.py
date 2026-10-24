"""
本周 AI 导读（gen_weekly_intro）

看板顶部的"执行摘要"：30 秒告诉研究者本周最该关注的 3 件事。
- headline：本周态势一句话
- must_read：3 条必看（跨方向，从本周高分候选里选，附一句 why，可点击）
- trend：一句话趋势判断

候选与看板"本周必看"口径一致（复用 pipeline.scoring）；paper_id 强制白名单校验防幻觉。
输出 data/weekly_intro.json，供 generate_html.py 顶部展示。
"""
import sys
import json
import time
from pathlib import Path
from datetime import datetime, timedelta

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.scoring import calc_score, calc_industry_score
from pipeline.llm_tagger import LLMTagger, load_env
from utils import find_latest_file

INTRO_PROMPT = """你是具身智能 / 机器人领域的资深研究主编。下面是本周（含近期）最值得关注的候选进展（学术论文、公司一手发布、开源/模型），以及本周跨源事件速览。
请从中挑出最不该错过的 3 件，给出一个"30 秒看懂本周"的导读。严格基于材料，不要编造；3 件尽量分布在不同方向（如 VLA、世界模型、仿真/数据、工业界发布）。

输出严格 JSON（不要多余文字）：
{{
  "headline": "本周态势一句话，25-40 字，点出最突出的主题或变化",
  "must_read": [
    {{"paper_id": "必须是下面候选列表里出现的 id，原样复制", "why": "一句话说清为什么必看，20-35 字，点出方法/开源/真机/里程碑意义"}}
  ],
  "trend": "一句话趋势判断，25-40 字，给研究者方向性的启发"
}}
must_read 恰好 3 条，paper_id 必须逐字来自候选列表。

==== 候选进展（[id] 标题 —— 摘要）====
{candidates}

==== 本周跨源事件速览（供参考，不要作为 must_read 的 id）====
{events}
"""


def parse_json_lenient(text):
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    lo, hi = text.find("{"), text.rfind("}")
    if lo != -1 and hi != -1:
        text = text[lo:hi + 1]
    return json.loads(text)


def load_all_papers():
    combined = json.load(open(PROJECT_ROOT / "data" / "combined.json", encoding="utf-8"))
    papers = combined if isinstance(combined, list) else combined.get("papers", [])
    backfill = find_latest_file(PROJECT_ROOT / "data" / "backfill", "arxiv_backfill_*.json")
    if backfill:
        bf = json.load(open(backfill, encoding="utf-8"))
        bf = bf if isinstance(bf, list) else bf.get("papers", [])
        existing = {p["id"] for p in papers}
        papers = papers + [p for p in bf if p["id"] not in existing]
    return papers


def build_candidates(papers):
    d7 = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    d30 = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

    acad = [p for p in papers if p.get("source_type") in ("arxiv", "openreview", "huggingface")
            and p.get("published_at", "")[:10] >= d7]
    for p in acad:
        p["_s"] = calc_score(p)
    acad = sorted(acad, key=lambda x: x["_s"], reverse=True)[:12]

    ind = [p for p in papers if p.get("source_type") in ("company_blog", "lab_blog")
           and p.get("published_at", "")[:10] >= d30]
    for p in ind:
        p["_s"] = calc_industry_score(p)
    ind = sorted(ind, key=lambda x: x["_s"], reverse=True)[:6]

    oss = [p for p in papers if p.get("source_type") in ("github", "huggingface")
           and p.get("published_at", "")[:10] >= d30]
    def heat(p):
        rm = p.get("raw_metadata") or {}
        return rm.get("stars", 0) or rm.get("likes", 0) or 0
    oss = sorted(oss, key=heat, reverse=True)[:6]

    return acad + ind + oss


def main():
    load_env()
    papers = load_all_papers()
    candidates = build_candidates(papers)
    valid_ids = {p["id"] for p in candidates}

    lines = []
    for p in candidates:
        ab = (p.get("abstract") or "").strip().replace("\n", " ")[:300]
        lines.append(f"[{p['id']}] {p.get('title','').strip()} —— {ab}")
    candidates_text = "\n".join(lines)

    # 事件速览
    events_text = "（无）"
    eb_path = PROJECT_ROOT / "data" / "event_briefs.json"
    if eb_path.exists():
        briefs = json.load(open(eb_path, encoding="utf-8")).get("briefs", {})
        ev_lines = [f"· {b.get('tldr','')}" for b in list(briefs.values())[:8]]
        if ev_lines:
            events_text = "\n".join(ev_lines)

    llm = LLMTagger(provider="deepseek")
    if not llm.api_key:
        print("错误：未设置 LLM_API_KEY")
        return

    prompt = INTRO_PROMPT.format(candidates=candidates_text, events=events_text)
    result = None
    for attempt in range(2):
        resp = llm._call_llm(prompt)
        if resp:
            try:
                result = parse_json_lenient(resp)
                break
            except Exception as e:
                print(f"解析失败(尝试{attempt+1}): {e}")
        time.sleep(2)

    if not result:
        print("导读生成失败")
        return

    # 校验 must_read 的 paper_id 白名单
    must = []
    for item in result.get("must_read", []):
        pid = item.get("paper_id", "")
        if pid in valid_ids and item.get("why"):
            must.append({"paper_id": pid, "why": str(item["why"]).strip()})
    must = must[:3]
    if len(must) < 3:
        print(f"警告：有效必读仅 {len(must)} 条")

    out = {
        "generated_at": datetime.now().isoformat(),
        "headline": str(result.get("headline", "")).strip(),
        "trend": str(result.get("trend", "")).strip(),
        "must_read": must,
    }
    out_path = PROJECT_ROOT / "data" / "weekly_intro.json"
    json.dump(out, open(out_path, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print(f"生成: {out_path}")
    print("headline:", out["headline"])
    for m in must:
        print("  -", m["paper_id"], "|", m["why"])


if __name__ == "__main__":
    main()
