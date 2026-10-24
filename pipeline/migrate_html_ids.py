"""
一次性迁移：把 combined.json 里公司 HTML 条目的 id 从内置 hash()（跨进程随机）
改为稳定的 URL slug，并同步 event_briefs.json 的 key。
修复后同一篇文章 id 不再随采集进程变化，事件解读缓存 / 已读 / 收藏不再失效。
"""
import json
import sys
from pathlib import Path
sys.path.insert(0, ".")
from collectors.company_html_collector import CompanyHTMLCollector

ROOT = Path(".")

def prefix(p):
    return f"html:{(p.get('source_name') or '').lower().replace(' ', '_')}:"

combined = json.load(open(ROOT / "data/combined.json", encoding="utf-8"))
papers = combined if isinstance(combined, list) else combined.get("papers", [])

id_map = {}
changed = 0
for p in papers:
    if str(p.get("id", "")).startswith("html:") and p.get("url"):
        new_id = prefix(p) + CompanyHTMLCollector._stable_id(p["url"])
        if new_id != p["id"]:
            id_map[p["id"]] = new_id
            p["id"] = new_id
            changed += 1
            # 同步 source_id 里的前缀无关（source_id 含 url，不用改）

print(f"HTML id 重算: {changed} 条")

# 检查新 id 是否有冲突
ids = [p["id"] for p in papers]
dups = {x for x in ids if ids.count(x) > 1}
print("id 冲突:", dups if dups else "无")

json.dump(combined, open(ROOT / "data/combined.json", "w", encoding="utf-8"),
          ensure_ascii=False, indent=2, default=str)

# 同步 event_briefs.json 的 key
eb_path = ROOT / "data" / "event_briefs.json"
if eb_path.exists():
    eb = json.load(open(eb_path, encoding="utf-8"))
    briefs = eb.get("briefs", {})
    new_briefs = {}
    for k, v in briefs.items():
        new_briefs[id_map.get(k, k)] = v
    eb["briefs"] = new_briefs
    json.dump(eb, open(eb_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("event_briefs key 同步:")
    for old, new in id_map.items():
        if old in briefs:
            print(f"  {old} -> {new}")
