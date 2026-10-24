"""
事件级 AI 解读生成（gen_event_briefs）

对跨源聚合事件（论文 + 官方 + 媒体 + 开源 + 模型）生成一段"30 秒看懂"的解读：
- tldr：一句话说清是什么进展
- what：解决什么问题、核心方法
- why：为什么值得关注（开源/真机/新能力/多源印证）

只基于事件成员材料，不编造；增量生成（已有解读的事件跳过，每日只对新事件调用）。
输出 data/event_briefs.json，供 generate_html.py 在事件卡片顶部展示。
"""
import sys
import json
import time
from pathlib import Path
from datetime import datetime, timedelta

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.event_merger import merge_events, SOURCE_LABEL
from pipeline.llm_tagger import LLMTagger, load_env
from utils import find_latest_file

WINDOW_DAYS = 120

EVENT_PROMPT = """你是具身智能 / 机器人领域的资深研究者。下面是「同一个进展」在多个来源的材料（学术论文、官方公告、媒体报道、开源代码、模型权重）。
请严格基于这些材料，输出一个 JSON 对象，帮研究者 30 秒看懂这件事。不要编造材料里没有的信息；若材料不足以判断，就只写能确定的部分。

输出格式（严格 JSON，不要多余文字）：
{{
  "tldr": "一句话说清这是什么进展，30-50 字，包含主体（机构/方法名）和做了什么",
  "what": "解决什么问题、核心方法或创新，60-100 字，可用分号分隔 1-2 点",
  "why": "为什么值得关注，点出开源、真机验证、新能力、多源印证或里程碑意义，40-70 字"
}}

本事件的多源材料：
{materials}
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
    """combined.json + backfill，和 generate_html 一致"""
    combined = json.load(open(PROJECT_ROOT / "data" / "combined.json", encoding="utf-8"))
    papers = combined if isinstance(combined, list) else combined.get("papers", [])
    backfill = find_latest_file(PROJECT_ROOT / "data" / "backfill", "arxiv_backfill_*.json")
    if backfill:
        bf = json.load(open(backfill, encoding="utf-8"))
        bf = bf if isinstance(bf, list) else bf.get("papers", [])
        existing = {p["id"] for p in papers}
        papers = papers + [p for p in bf if p["id"] not in existing]
    return papers


def build_materials(ev, pidx):
    parts = []
    for mid in ev["members"]:
        p = pidx.get(mid)
        if not p:
            continue
        stype = p.get("source_type", "arxiv")
        label = SOURCE_LABEL.get(stype, "来源")
        title = p.get("title", "").strip()
        abstract = (p.get("abstract") or "").strip().replace("\n", " ")
        rm = p.get("raw_metadata") or {}
        extra = ""
        if stype == "github":
            if rm.get("tag"):
                extra = f"（版本 {rm['tag']}，{rm.get('stars','?')} stars）"
            else:
                extra = f"（新开源，{rm.get('stars','?')} stars）"
        elif stype == "huggingface":
            extra = f"（模型权重，{rm.get('likes','?')} likes，{rm.get('downloads','?')} 下载）"
        snippet = abstract[:600] if abstract else "（无摘要）"
        parts.append(f"[{label}]{extra} {title}\n{snippet}")
    return "\n\n".join(parts)


def main(force=False):
    load_env()
    papers = load_all_papers()
    pidx = {p["id"]: p for p in papers}

    result = merge_events(papers)
    events = list(result["events"].values())

    cutoff = (datetime.now() - timedelta(days=WINDOW_DAYS)).strftime("%Y-%m-%d")
    # 只对跨源事件（成员含 >=2 种来源类型）生成
    targets = []
    for ev in events:
        types = {pidx.get(m, {}).get("source_type", "arxiv") for m in ev["members"] if m in pidx}
        if len(types) < 2:
            continue
        pdate = str(pidx.get(ev["primary"], {}).get("published_at", ""))[:10]
        if pdate < cutoff:
            continue
        targets.append(ev)
    targets.sort(key=lambda e: str(pidx.get(e["primary"], {}).get("published_at", "")), reverse=True)
    print(f"近 {WINDOW_DAYS} 天跨源事件: {len(targets)} 个")

    # 已有解读（增量）
    out_path = PROJECT_ROOT / "data" / "event_briefs.json"
    briefs = {}
    if out_path.exists():
        try:
            briefs = json.load(open(out_path, encoding="utf-8")).get("briefs", {})
        except Exception:
            briefs = {}

    llm = LLMTagger(provider="deepseek")
    if not llm.api_key:
        print("错误：未设置 LLM_API_KEY，跳过事件解读")
        return

    new_count = 0
    for ev in targets:
        eid = ev["primary"]
        if not force and eid in briefs:
            continue
        primary = pidx.get(eid, {})
        print(f"  解读: {primary.get('title','')[:50]}")
        materials = build_materials(ev, pidx)
        prompt = EVENT_PROMPT.format(materials=materials)
        parsed = None
        for attempt in range(2):
            resp = llm._call_llm(prompt)
            if resp:
                try:
                    parsed = parse_json_lenient(resp)
                    break
                except Exception as e:
                    print(f"    解析失败(尝试{attempt+1}): {e}")
            time.sleep(2)
        if parsed and parsed.get("tldr"):
            briefs[eid] = {
                "tldr": str(parsed.get("tldr", "")).strip(),
                "what": str(parsed.get("what", "")).strip(),
                "why": str(parsed.get("why", "")).strip(),
            }
            new_count += 1
            print("    OK")
        else:
            print("    失败，跳过")
        time.sleep(1)

    json.dump({"generated_at": datetime.now().isoformat(),
               "window_days": WINDOW_DAYS,
               "briefs": briefs},
              open(out_path, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print(f"\n生成: {out_path}（新增 {new_count}，共 {len(briefs)} 条事件解读）")


if __name__ == "__main__":
    main(force="--force" in sys.argv)
