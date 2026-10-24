"""
事件归并器（Event Merger）
=========================
把"同一进展在多个平台的发布"归并成一个事件：
- 同一工作的 arXiv 论文 + 公司官方博客 + 媒体报道 -> 聚合成一张事件卡
- 这是本看板相对搜索引擎的核心价值：自动识别"这几条讲的是同一件事"

设计原则（精度优先，宁缺毋滥）：
- 只用确定性规则，不依赖 LLM（免费、可复现、可审计）
- 高置信归并信号：
  1. 标题高相似：归一化后 Jaccard >= 0.75（公司博客常直接转发论文标题，如 TIGER）
  2. 高区分度型号指纹（camelCase 专名 / 带版本号型号），且两标题有实质 token 重叠
     —— 排除"泛泛提及 OpenAI/ChatGPT/会议名"的跨主题误配
- 时间窗：默认 ±30 天
- 用并查集（Union-Find）支持传递性聚类（A~B, B~C => A,B,C 同事件）

型号指纹刻意不使用"全大写普通词"（TIGER/COSMOS/ATLAS）与"连字符术语"
（world-action/zero-shot/large-scale）——它们在 arXiv 标题里歧义太大，
这类改由信号 1（标题高相似）或后续 LLM 增强覆盖。
"""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timedelta
from typing import List, Dict, Any, Tuple

# 学术会议/年份不应当成型号（两家公司同参 IROS 不是同一事件）
CONF_TOKENS = {
    "IROS", "CORL", "ICRA", "ICCV", "CVPR", "RSS", "NEURIPS", "ICML", "ICLR",
    "AAAI", "ECCV", "ROBOCON", "HRI", "CASE", "WORKSHOP", "SYMPOSIUM",
}

# 标题归一化时的弱停用词
_STOPWORDS = {
    "the", "and", "for", "with", "via", "from", "using", "toward", "towards",
    "novel", "new", "into", "over", "based", "its", "are", "can", "this", "that",
    "when", "where", "which", "our", "also", "more", "most", "across", "but",
    "not", "how", "why", "what", "all", "you", "your", "an", "was", "were",
    "may", "be", "is", "to", "of", "in", "on", "at", "by", "as", "we",
}

# 主条目类型优先级（数字越小越权威）：一手技术 > 一手官方 > 媒体报道
_TYPE_RANK = {
    "arxiv": 0, "openreview": 0, "huggingface": 0, "github": 0,
    "company_blog": 1, "lab_blog": 1, "x_thread": 1,
    "media": 2,
}

# 前端展示用的来源类型中文标签
SOURCE_LABEL = {
    "arxiv": "论文", "openreview": "论文", "huggingface": "模型",
    "github": "开源", "company_blog": "官方", "lab_blog": "官方",
    "x_thread": "X", "media": "媒体",
}


def _parse_date(s: str):
    try:
        return datetime.strptime((s or "")[:10], "%Y-%m-%d")
    except (ValueError, TypeError):
        return None


def _norm_ascii(title: str) -> str:
    """把中文/标点替换为空格（保留连字符、点、π），解决中文紧贴英文时
    \\b 词边界失效（如「银河通用DualWAM」提取不到 DualWAM）。"""
    return re.sub(r"[^A-Za-z0-9π.\- ]", " ", title or "")


def unique_fingerprints(title: str) -> set:
    """提取「独特型号」指纹（小写归一），跨来源命中即高度可信，可放宽
    标题 token 重叠门槛（对中文博客尤其重要——中文标题几乎没有英文 token）。

    两类：
    - 全大写连字符型号：WAM-TTT / V-JEPA / RT-TFM（片段全大写，区别于 world-action）
    - camelCase 专名（长度>=6）：DualWAM / RobotAPO / DreamTrue / PingpongDuo
    """
    t = _norm_ascii(title)
    out = set()
    # A) 全大写连字符型号：至少两个片段，每段 >=2 个字母/数字
    for m in re.finditer(
        r"(?<![A-Za-z0-9])([A-Z]{2,}(?:-[A-Z0-9]{2,})+)(?![A-Za-z0-9])", t
    ):
        out.add(m.group(1).lower())
    # B) camelCase 专名（大写词头 + 小写片段 + 再大写，总长度 >=6）
    for m in re.finditer(
        r"(?<![A-Za-z])([A-Z][a-z]{1,}[A-Z][A-Za-z0-9]{2,})(?![A-Za-z])", t
    ):
        out.add(m.group(1).lower())
    return out


def model_fingerprints(title: str) -> set:
    """提取高区分度型号指纹（小写归一）。

    仅保留两类高精度信号：
    - camelCase 专名：PingpongDuo / AstraTennis / HiPHI / GeoMem / ChatGPT
    - 带版本号型号：H2 / X2 / GR00T / Digit 5 / Helix 2.5 / π0.5 / AGILE 2.0
    """
    t = _norm_ascii(title)
    out = set()

    # 1) camelCase 专名：大写词头 + 小写片段 + 再出现大写
    for m in re.finditer(r"\b([A-Z][a-z]{1,}[A-Z][A-Za-z0-9]+)\b", t):
        out.add(m.group(1).lower())

    # 2) 字母 + 数字版本号（字母与数字间允许一个空格）
    for m in re.finditer(
        r"(?<![A-Za-z])((?:π|pi)\s?\d(?:\.\d+)?|[A-Z][A-Za-z]{0,6} ?\d(?:\.\d+)?)\b", t
    ):
        raw = m.group(1)
        # 排除"会议名 + 年份"（IROS 2026 / CoRL 2026）
        before = t[max(0, m.start() - 8):m.start()].upper()
        if any(c in before for c in CONF_TOKENS):
            continue
        norm = re.sub(r"\s+", "", raw).lower().replace("pi", "π")
        letters = re.sub(r"[^a-zπ]", "", norm)
        numpart = re.sub(r"[^0-9.]", "", norm)
        if len(letters) < 1:
            continue
        # 排除数量/年份（>30 的纯数字尾巴，如 100、200K、10000）
        if numpart and re.fullmatch(r"\d+(\.\d+)?", numpart):
            try:
                if float(numpart) > 30:
                    continue
            except ValueError:
                continue
        out.add(norm)

    return out


def _title_tokens(title: str) -> set:
    t = re.sub(r"[^A-Za-z0-9π ]", " ", (title or "").lower())
    return {w for w in t.split() if len(w) > 2 and w not in _STOPWORDS}


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


class _UnionFind:
    def __init__(self, n: int):
        self.parent = list(range(n))

    def find(self, x: int) -> int:
        root = x
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[x] != root:
            self.parent[x], x = root, self.parent[x]
        return root

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)


def merge_events(papers: List[Dict[str, Any]],
                 sim_threshold: float = 0.75,
                 window_days: int = 30,
                 min_token_overlap: int = 3) -> Dict[str, Any]:
    """把扁平论文列表归并为事件。

    返回:
        {
          "events": {event_id: {"members": [idx,...], "primary": idx}},
          "index": {paper_id: event_id},
        }
    并在每条 paper dict 上原地写入:
        event_id, event_size, event_primary(bool), event_members(同事件其它条目 id)
    """
    n = len(papers)
    uf = _UnionFind(n)

    fps = [model_fingerprints(p.get("title", "")) for p in papers]
    ufps = [unique_fingerprints(p.get("title", "")) for p in papers]
    toks = [_title_tokens(p.get("title", "")) for p in papers]
    dates = [_parse_date(p.get("published_at", "")) for p in papers]

    # 型号指纹倒排索引
    fp_index: Dict[str, List[int]] = defaultdict(list)
    for i, s in enumerate(fps):
        for fp in s:
            fp_index[fp].append(i)

    # 独特型号指纹倒排索引（WAM-TTT / DualWAM 等）
    ufp_index: Dict[str, List[int]] = defaultdict(list)
    for i, s in enumerate(ufps):
        for fp in s:
            ufp_index[fp].append(i)

    def _within_window(i: int, j: int) -> bool:
        if dates[i] and dates[j]:
            return abs((dates[i] - dates[j]).days) <= window_days
        return True

    def _cross_source(i: int, j: int) -> bool:
        return papers[i].get("source_name") != papers[j].get("source_name")

    # 信号 0（最强）：独特型号（WAM-TTT / DualWAM）跨来源命中即归并。
    # 独特型号本身就是唯一标识，不强求标题 token 重叠（中英文标题几乎无重叠）。
    for fp, idxs in ufp_index.items():
        for a in range(len(idxs)):
            for b in range(a + 1, len(idxs)):
                i, j = idxs[a], idxs[b]
                if _cross_source(i, j) and _within_window(i, j):
                    uf.union(i, j)

    # 信号 2：型号指纹匹配 + 实质 token 重叠
    for fp, idxs in fp_index.items():
        for a in range(len(idxs)):
            for b in range(a + 1, len(idxs)):
                i, j = idxs[a], idxs[b]
                if not _cross_source(i, j):
                    continue
                if not _within_window(i, j):
                    continue
                if len(toks[i] & toks[j]) >= min_token_overlap:
                    uf.union(i, j)

    # 信号 1：标题高 Jaccard（O(n^2)，但单页数据规模可控；加日期粗筛）
    for i in range(n):
        for j in range(i + 1, n):
            if not _cross_source(i, j):
                continue
            if not _within_window(i, j):
                continue
            inter = len(toks[i] & toks[j])
            if inter < 4:
                continue
            sim = _jaccard(toks[i], toks[j])
            if sim >= sim_threshold:
                uf.union(i, j)

    # 收集事件簇
    clusters: Dict[int, List[int]] = defaultdict(list)
    for i in range(n):
        clusters[uf.find(i)].append(i)

    events: Dict[str, Dict[str, Any]] = {}
    index: Dict[str, str] = {}

    for root, members in clusters.items():
        if len(members) == 1:
            continue  # 单条不成事件
        # 选主条目：类型权威优先，其次日期更新、标题更长
        def _key(i: int):
            p = papers[i]
            return (
                _TYPE_RANK.get(p.get("source_type", "media"), 3),
                -(dates[i].timestamp() if dates[i] else 0),
                -len(p.get("title", "")),
            )
        members_sorted = sorted(members, key=_key)
        primary = members_sorted[0]
        primary_id = papers[primary].get("id")
        event_id = f"evt_{primary_id}"

        member_ids = [papers[i].get("id") for i in members_sorted]
        events[event_id] = {
            "primary": primary_id,
            "members": member_ids,
            "size": len(members_sorted),
        }
        for i in members_sorted:
            pid = papers[i].get("id")
            index[pid] = event_id
            papers[i]["event_id"] = event_id
            papers[i]["event_size"] = len(members_sorted)
            papers[i]["event_primary"] = (i == primary)
            papers[i]["event_members"] = [
                m for m in member_ids if m != pid
            ]

    return {"events": events, "index": index}


if __name__ == "__main__":
    import json
    data = json.load(open("data/combined.json", encoding="utf-8"))
    res = merge_events(data)
    print(f"归并事件数: {len(res['events'])}")
    by_id = {p["id"]: p for p in data}
    for eid, ev in res["events"].items():
        print(f"\n{eid} ({ev['size']} 个来源)")
        for pid in ev["members"]:
            p = by_id[pid]
            tag = "★主" if pid == ev["primary"] else "  "
            print(f"  {tag} [{SOURCE_LABEL.get(p.get('source_type'), '?')}] "
                  f"{p.get('source_name','')[:14]} | {p.get('title','')[:60]}")
