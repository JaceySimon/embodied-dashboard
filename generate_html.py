"""
生成静态 HTML 展示页 v4
增加：收藏功能、相关论文推荐、更好的交互
"""
import json
import html
from pathlib import Path
from collections import Counter
from datetime import datetime, timedelta, timezone

PROJECT_ROOT = Path(__file__).parent

# 自动查找最新数据文件
import sys
sys.path.insert(0, str(PROJECT_ROOT))
from utils import find_latest_file

# 读取数据（优先读合并后的，没有则回退到最新 arXiv backfill）
combined_path = PROJECT_ROOT / "data" / "combined.json"
latest_backfill = find_latest_file(PROJECT_ROOT / "data" / "backfill", "arxiv_backfill_*.json")

if combined_path.exists():
    with open(combined_path, "r", encoding="utf-8") as f:
        papers = json.load(f)
elif latest_backfill:
    with open(latest_backfill, "r", encoding="utf-8") as f:
        papers = json.load(f)
else:
    print("错误：没有找到数据文件，请先跑 python run.py backfill 90")
    papers = []

# 按时间倒序
papers.sort(key=lambda p: p["published_at"], reverse=True)

# 事件归并：把同一进展的 arXiv 论文 / 官方博客 / 媒体报道聚合成一个事件
from pipeline.event_merger import merge_events, SOURCE_LABEL
event_result = merge_events(papers)
papers_by_id = {p["id"]: p for p in papers}

# 统计标签
tag_count = Counter()
for p in papers:
    for t in p["tags"]:
        tag_count[t] += 1

top_tags = tag_count.most_common(20)

# 计算本周热点
week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
week_papers = [p for p in papers if p["published_at"] >= week_ago]
hot_tags = Counter()
for p in week_papers:
    for t in p["tags"]:
        hot_tags[t] += 1
hot_tags_top = hot_tags.most_common(10)

# 计算本周必看 10 篇（按重要性评分）
from pipeline.scoring import calc_score, calc_industry_score

# 给本周论文打分
for p in week_papers:
    p["score"] = calc_score(p)

# 本周必看 = 学术 Top 7（近 7 天，arXiv/OpenReview）+ 工业界 Top 3（近 30 天，
# 公司/实验室一手源——工业界发布频率低、生命周期长，用更宽窗口）+ 开源 Top 2（近 30 天 GitHub）
week_academic = sorted(
    [p for p in week_papers if p.get("source_type") in ("arxiv", "openreview", "huggingface")],
    key=lambda x: x["score"], reverse=True)[:7]

ind_ago = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
# 本周必看的工业界槽位只放公司/实验室一手源（媒体是二手报道，且合集/广告多，留在卡片流）
industry_papers = [p for p in papers
                   if p.get("source_type") in ("company_blog", "lab_blog")
                   and p["published_at"] >= ind_ago]
for p in industry_papers:
    p["ind_score"] = calc_industry_score(p)
week_industry = sorted(industry_papers, key=lambda x: x["ind_score"], reverse=True)[:3]

# 开源槽位：近 30 天 = 1 个框架 release + 1 个最高 star 新开源 + 1 个最热 HF 模型
def _oss_heat(p):
    rm = p.get("raw_metadata") or {}
    return rm.get("stars", 0) or rm.get("likes", 0) or 0

opensource_papers = [p for p in papers
                     if p.get("source_type") in ("github", "huggingface")
                     and p["published_at"] >= ind_ago]
_gh_releases = [p for p in opensource_papers if p.get("source_type") == "github"
                and str(p.get("id","")).count(":") >= 2]
_gh_new = [p for p in opensource_papers if p.get("source_type") == "github"
           and str(p.get("id","")).count(":") < 2]
_hf_new = [p for p in opensource_papers if p.get("source_type") == "huggingface"]
week_opensource = (sorted(_gh_releases, key=lambda x: x["published_at"], reverse=True)[:1] +
                   sorted(_gh_new, key=_oss_heat, reverse=True)[:1] +
                   sorted(_hf_new, key=_oss_heat, reverse=True)[:1])

# 学术 7 + 工业 3 + 开源 2，各自带分区标记
week_top = ([dict(p, _zone="academic") for p in week_academic] +
            [dict(p, _zone="industry") for p in week_industry] +
            [dict(p, _zone="opensource") for p in week_opensource])

# ============ 领域脉搏：方向热度 + 机构活跃榜 ============
from collections import Counter as _Counter
PULSE_TAGS = [("VLA", "VLA"), ("world_model", "世界模型"), ("manipulation", "操作"),
              ("locomotion", "运动"), ("sim2real", "Sim2Real"),
              ("foundation_model", "基座模型"), ("diffusion_policy", "Diffusion Policy")]
_week7 = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
_tag_counts = _Counter()
for _p in papers:
    if _p.get("published_at", "")[:10] >= _week7:
        for _t, _label in PULSE_TAGS:
            if _t in (_p.get("tags") or []):
                _tag_counts[_label] += 1
pulse_dirs = _tag_counts.most_common(6)

# 机构名归一化（一手源 / 开源 / 模型）
_ORG_ALIASES = {
    "agibot": "智元机器人", "agibot agibot": "智元机器人",
    "nvidia research blog": "NVIDIA",
    "google deepmind research": "Google DeepMind",
    "mujoco": "MuJoCo", "isaaclab": "NVIDIA Isaac", "isaacsim": "NVIDIA Isaac",
}
def _org_name(p):
    n = p.get("source_name", "")
    for suf in [" · GitHub", " · Hugging Face", " · Company Blog", " · Lab Blog",
                " Research Blog", " Research", " AgiBot", " Galbot"]:
        n = n.replace(suf, "")
    # 处理 "mujoco · Release" 这种
    n = n.split(" · ")[0]
    return _ORG_ALIASES.get(n.strip().lower(), n.strip())

_month30 = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
_org_counts = _Counter()
for _p in papers:
    if _p.get("published_at", "")[:10] >= _month30 and \
       _p.get("source_type") in ("company_blog", "lab_blog", "github", "huggingface"):
        _org_counts[_org_name(_p)] += 1
pulse_orgs = [(n, c) for n, c in _org_counts.most_common(10) if n and c >= 1][:9]

# 方向趋势：近 12 周各方向每周论文数（看哪个方向在升温）
TREND_TAGS = [("VLA", "VLA"), ("world_model", "世界模型"),
              ("humanoid", "人形"), ("sim2real", "Sim2Real")]
TREND_WEEKS = 12
_now = datetime.now()
_trend = {label: [0] * TREND_WEEKS for _, label in TREND_TAGS}
for _p in papers:
    try:
        _d = datetime.strptime(_p.get("published_at", "")[:10], "%Y-%m-%d")
    except Exception:
        continue
    _days = (_now - _d).days
    if 0 <= _days < TREND_WEEKS * 7:
        _bucket = TREND_WEEKS - 1 - _days // 7
        for _t, _label in TREND_TAGS:
            if _t in (_p.get("tags") or []):
                _trend[_label][_bucket] += 1
trend_data = {
    "labels": [f"W-{TREND_WEEKS-1-i}" for i in range(TREND_WEEKS)],
    "series": [{"name": k, "data": v} for k, v in _trend.items()],
}
trend_labels_json = json.dumps([f"{i+1}周前" if i < TREND_WEEKS-1 else "本周"
                                for i in range(TREND_WEEKS)][::-1], ensure_ascii=False)
trend_series_json = json.dumps(
    [{"name": k, "data": v} for k, v in _trend.items()], ensure_ascii=False)


# ============ 智能资源链接：从 code_url / raw_metadata / abstract 提取代码/项目/数据集 ============
import re as _re
_URL_RE = _re.compile(r"https?://[^\s\)\]\}>，。；;]+")
_GH_RE = _re.compile(r"https?://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
def _clean_url(u):
    u = u.rstrip(".,;)']")
    if u.lower().endswith(".git"):
        u = u[:-4]
    return u
def _resource_links(p):
    """返回 [(key, url, label, icon)]，去重，最多 3 个；key: code/page/data"""
    rm = p.get("raw_metadata") or {}
    found = {}
    def add(key, url, label, icon):
        url = _clean_url(url or "")
        low = url.lower()
        # 过滤视频 / 非资源链接
        if any(x in low for x in ("youtu.be", "youtube.com", "vimeo.com", ".mp4")):
            return
        if url and key not in found:
            found[key] = (url, label, icon)
    # 1) 结构化字段（arxiv comment 提取）
    add("code", p.get("code_url") or rm.get("code"), "代码", "🐙")
    add("page", rm.get("project_page"), "项目主页", "🌐")
    add("data", rm.get("dataset"), "数据集", "🤗")
    # 2) 兜底：从摘要里找 GitHub / 项目主页 / 数据集
    text = (p.get("abstract") or "")
    if "code" not in found:
        for m in _GH_RE.findall(text):
            u = _clean_url(m)
            if not u.lower().endswith((".pdf", ".png", ".jpg")):
                add("code", u, "代码", "🐙")
                break
    if "page" not in found:
        for m in _URL_RE.findall(text):
            u = _clean_url(m)
            low = u.lower()
            if "github.com" in low:
                continue
            if "project" in low or low.endswith("github.io") or ".github.io/" in low:
                add("page", u, "项目主页", "🌐")
                break
    if "data" not in found:
        for m in _URL_RE.findall(text):
            if "huggingface.co/datasets" in m.lower():
                add("data", m, "数据集", "🤗")
                break
    return [(k, v[0], v[1], v[2]) for k, v in found.items()]

# 生成论文卡片
_INTERNAL_TAGS = {"open_source", "hf_model", "gh_release"}
def _public_tags(tags, limit=5):
    shown = [t for t in (tags or []) if t not in _INTERNAL_TAGS]
    return shown[:limit]

def render_paper(p):
    tags_html = "".join([f'<span class="tag">{html.escape(t)}</span>' for t in _public_tags(p["tags"])])
    
    # 来源类型徽章
    source_type = p.get("source_type", "arxiv")
    source_name = p.get("source_name", "arXiv")
    
    if source_type in ("company_blog", "lab_blog"):
        source_badge = f'<span class="badge badge-industry">{html.escape(source_name)}</span>'
        source_group = "industry"
    elif source_type == "media":
        source_badge = f'<span class="badge badge-media">{html.escape(source_name)}</span>'
        source_group = "media"
    elif source_type == "github":
        source_badge = f'<span class="badge badge-github">开源 · {html.escape(source_name.replace(" · GitHub",""))}</span>'
        source_group = "github"
    elif source_type == "huggingface":
        source_badge = f'<span class="badge badge-hf">模型 · {html.escape(source_name.replace(" · Hugging Face",""))}</span>'
        source_group = "huggingface"
    else:
        source_badge = '<span class="badge badge-academic">学术</span>'
        source_group = "arxiv"
    
    # 作者（RSS 可能没有作者；开源/模型卡片徽章已含机构，不重复显示来源名）
    authors_list = p.get("authors", [])
    if authors_list:
        authors = ", ".join(authors_list[:3])
        if len(authors_list) > 3:
            authors += " et al."
    elif source_type in ("github", "huggingface"):
        authors = ""
    else:
        authors = source_name
    
    # 摘要
    abstract_text = p.get("abstract", "") or ""
    abstract = html.escape(abstract_text[:150] + "..." if len(abstract_text) > 150 else abstract_text)
    
    # 标签数据
    tags_data = " ".join(p.get("tags", []))
    has_real = "true" if p.get("has_real_robot", False) else "false"
    has_open = "true" if p.get("is_open_source", False) else "false"
    
    # 论文 ID（用于收藏）
    paper_id = str(p["id"]).replace("/", "_")

    # 一键 BibTeX（仅学术论文；数据齐备）
    bibtex_attr = ""
    cite_link = ""
    if source_type == "arxiv":
        _aid = str(p["id"]).split("arxiv:", 1)[-1]
        _aid = _aid.split("v")[0] if _aid[:1].isdigit() and "v" in _aid.split("/")[-1] else _aid
        _year = str(p.get("published_at", ""))[:4]
        _alist = p.get("authors", []) or []
        def _bib_author(name):
            parts = name.strip().split()
            if len(parts) >= 2:
                return parts[-1] + ", " + " ".join(parts[:-1])
            return name.strip()
        _bib_authors = " and ".join(_bib_author(a) for a in _alist) or "Unknown"
        _firstlast = (_alist[0].strip().split()[-1] if _alist else "anon").lower()
        _key = f"{_firstlast}{_year}"
        _btitle = p.get("title", "").replace("{", "").replace("}", "")
        _bib = (f"@article{{{_key},\n"
                f"  title={{{_btitle}}},\n"
                f"  author={{{_bib_authors}}},\n"
                f"  journal={{arXiv preprint arXiv:{_aid}}},\n"
                f"  year={{{_year}}}\n}}}}")
        bibtex_attr = f' data-bibtex="{html.escape(_bib, quote=True)}"'
        cite_link = f'<a href="javascript:void(0)" onclick="copyBib(\'{paper_id}\')">引用</a>'

    
    # 链接文本
    if source_type == "github":
        link_text = "Release" if str(p.get("id","")).count(":") >= 2 else "GitHub 仓库"
    elif source_type == "huggingface":
        link_text = "Hugging Face"
    else:
        link_text = "阅读原文" if source_type != "arxiv" else "arXiv"

    # 开源/模型附加信息（stars / likes / 新开源标记）
    gh_meta = ""
    rm = p.get("raw_metadata") or {}
    if source_type == "github":
        if rm.get("new_open_source"):
            gh_meta += '<span class="gh-new">🆕 新开源</span>'
        if rm.get("stars") is not None:
            gh_meta += f'<span class="gh-stars">⭐ {rm.get("stars")}</span>'
    elif source_type == "huggingface":
        if rm.get("likes") is not None:
            gh_meta += f'<span class="hf-likes">🤍 {rm.get("likes")}</span>'

    # 事件多源归并：主卡片渲染“同一进展的其他来源”，非主卡片默认折叠隐藏
    event_id = p.get("event_id", "")
    is_dup = "0" if p.get("event_primary", True) else "1"
    event_sources_html = ""
    if p.get("event_primary", True) and p.get("event_members"):
        member_items = []
        for mid in p["event_members"]:
            mp = papers_by_id.get(mid)
            if not mp:
                continue
            mtype = mp.get("source_type", "arxiv")
            mlabel = SOURCE_LABEL.get(mtype, "其他")
            mname = mp.get("source_name", "")
            mtitle = mp.get("title", "")
            murl = mp.get("url", "")
            member_items.append(
                f'<a class="event-source-link" href="{murl}" target="_blank">'
                f'<span class="es-tag es-{mtype}">{html.escape(mlabel)}</span>'
                f'<span class="es-title">{html.escape(mname)}</span>'
                f'<span class="es-name">{html.escape(mtitle[:70])}</span></a>'
            )
        n = p.get("event_size", 1)
        labels = " · ".join(dict.fromkeys(
            [SOURCE_LABEL.get(papers_by_id[mid].get("source_type", "arxiv"), "其他")
             for mid in [p["id"]] + p["event_members"] if mid in papers_by_id]
        ))
        if member_items:
            event_sources_html = (
                f'<details class="event-sources"><summary>'
                f'🔗 同一进展 · {n} 个来源（{labels}）</summary>'
                f'<div class="event-source-list">{"".join(member_items)}</div></details>'
            )

    # 智能资源链接（代码 / 项目主页 / 数据集）
    _res = _resource_links(p)
    resources_html = "".join([
        f'<a class="res-link res-{k}" href="{html.escape(u)}" target="_blank" rel="noopener" onclick="markRead(\'{paper_id}\')">{icon} {label}</a>'
        for k, u, label, icon in _res
    ])

    return f"""
    <div class="paper-card" data-id="{paper_id}" data-tags="{html.escape(tags_data)}" data-real="{has_real}" data-open="{has_open}" data-date="{str(p['published_at'])[:10]}" data-source="{source_group}" data-event-dup="{is_dup}" data-event-id="{html.escape(event_id)}"{bibtex_attr}>
        <div class="paper-header">
            <div class="paper-title"><a href="{p['url']}" target="_blank" onclick="markRead('{paper_id}')">{html.escape(p['title'])}</a></div>
            <div class="card-actions">
                <button class="read-btn" onclick="toggleRead('{paper_id}')" title="标记已读 / 未读">◯</button>
                <button class="fav-btn" onclick="toggleFav('{paper_id}')">☆</button>
            </div>
        </div>
        <div class="paper-meta">
            {source_badge}
            <span class="paper-authors">{html.escape(authors)}</span>
            <span class="paper-date">{str(p['published_at'])[:10]}</span>
            {gh_meta}
        </div>
        <div class="paper-tags">{tags_html}</div>
        <div class="paper-abstract">{abstract}</div>
        {event_sources_html}
        <div class="paper-links">
            <a href="{p['url']}" target="_blank" onclick="markRead('{paper_id}')">{link_text}</a>
            {resources_html}
            <a href="javascript:void(0)" onclick="showRelated('{paper_id}')">相关论文</a>
            {cite_link}
        </div>
    </div>
    """

papers_html = "\n".join([render_paper(p) for p in papers])

# ============ 重要进展（事件）专区：按"事件"看全貌，一个进展所有来源一次看完 ============
def _event_sort_key(ev):
    primary = papers_by_id.get(ev["primary"])
    date = primary.get("published_at", "") if primary else ""
    return (date, ev["size"])

# 仅展示近 120 天事件（与 backfill 一致），最多 12 个
_events_sorted = sorted(event_result["events"].values(),
                        key=_event_sort_key, reverse=True)
_event_window = (datetime.now() - timedelta(days=120)).strftime("%Y-%m-%d")
recent_events = [
    ev for ev in _events_sorted
    if papers_by_id.get(ev["primary"], {}).get("published_at", "") >= _event_window
][:12]

# 事件级 AI 解读（必须在 render_event_card 调用前加载）
event_brief_path = PROJECT_ROOT / "data" / "event_briefs.json"
event_briefs = {}
if event_brief_path.exists():
    try:
        event_briefs = json.load(open(event_brief_path, encoding="utf-8")).get("briefs", {})
    except Exception:
        event_briefs = {}

# 本周 AI 导读（顶部执行摘要）
intro_data = {}
intro_path = PROJECT_ROOT / "data" / "weekly_intro.json"
if intro_path.exists():
    try:
        intro_data = json.load(open(intro_path, encoding="utf-8"))
    except Exception:
        intro_data = {}
intro_html = ""
if intro_data.get("must_read"):
    _items = []
    for i, m in enumerate(intro_data["must_read"], 1):
        mp = papers_by_id.get(m["paper_id"])
        if not mp:
            continue
        _items.append(
            f'<div class="intro-item">'
            f'<a class="intro-title" href="{mp.get("url","")}" target="_blank" onclick="markRead(\'{str(mp["id"]).replace("/","_")}\')">'
            f'<span class="intro-num">{i}</span>{html.escape(mp.get("title",""))}</a>'
            f'<div class="intro-why">{html.escape(m.get("why",""))}</div></div>'
        )
    _headline = html.escape(intro_data.get("headline", ""))
    _trend = html.escape(intro_data.get("trend", ""))
    intro_html = (
        '<div class="intro-section">'
        '<div class="intro-head"><span class="ai-badge">AI 本周导读</span>'
        f'<span class="intro-headline">{_headline}</span></div>'
        f'<div class="intro-items">{"".join(_items)}</div>'
        f'<div class="intro-trend"><span class="intro-trend-label">趋势</span>{_trend}</div>'
        '</div>'
    )

def render_event_card(ev):
    primary = papers_by_id.get(ev["primary"])
    if not primary:
        return ""
    ptype = primary.get("source_type", "arxiv")
    plabel = SOURCE_LABEL.get(ptype, "论文")
    pdate = str(primary.get("published_at", ""))[:10]

    # 所有成员来源（主条目 + 其余），类型徽章 + 名称 + 直达链接
    member_links = []
    labels = []
    for mid in ev["members"]:
        mp = papers_by_id.get(mid)
        if not mp:
            continue
        mtype = mp.get("source_type", "arxiv")
        labels.append(SOURCE_LABEL.get(mtype, "其他"))
        member_links.append(
            f'<a class="ev-src-link" href="{mp.get("url","")}" target="_blank" '
            f'title="{html.escape(mp.get("title",""))}">'
            f'<span class="es-tag es-{mtype}">{html.escape(SOURCE_LABEL.get(mtype,"其他"))}</span>'
            f'{html.escape(mp.get("source_name",""))}</a>'
        )
    labels = " · ".join(dict.fromkeys(labels))
    # AI 事件解读（tldr 常显，方法/看点折叠）
    eb = event_briefs.get(ev["primary"])
    brief_html = ""
    if eb:
        brief_html = (
            '<div class="event-brief">'
            f'<div class="eb-tldr"><span class="ai-badge">AI 解读</span>{html.escape(eb.get("tldr",""))}</div>'
            '<details class="eb-more"><summary>方法与看点</summary>'
            f'<p class="eb-what"><b>方法</b>{html.escape(eb.get("what",""))}</p>'
            f'<p class="eb-why"><b>看点</b>{html.escape(eb.get("why",""))}</p>'
            '</details></div>'
        )
    return f"""
    <div class="event-card" data-date="{pdate}">
        <div class="event-card-title">
            <a href="{primary.get('url','')}" target="_blank">{html.escape(primary.get('title',''))}</a>
        </div>
        <div class="event-card-meta">
            <span class="es-tag es-{ptype}">{html.escape(plabel)}</span>
            <span class="event-card-date">{pdate}</span>
            <span class="event-card-count">{ev['size']} 个来源（{labels}）</span>
        </div>
        {brief_html}
        <div class="event-card-sources">{''.join(member_links)}</div>
    </div>
    """

events_html = "\n".join([render_event_card(ev) for ev in recent_events])

# ============ 领域脉搏（方向热度 + 机构活跃榜）============
_label_to_tag = {label: key for key, label in PULSE_TAGS}
if pulse_dirs:
    _max_dir = max(c for _, c in pulse_dirs)
    _dir_bars = []
    for _label, _c in pulse_dirs:
        _w = int(_c / _max_dir * 100)
        _key = _label_to_tag.get(_label, "")
        _dir_bars.append(
            f'<div class="pulse-row" onclick="filterByTag(\'{_key}\')">'
            f'<span class="pulse-label">{html.escape(_label)}</span>'
            f'<span class="pulse-track"><span class="pulse-fill" style="width:{_w}%"></span></span>'
            f'<span class="pulse-num">{_c}</span></div>')
    pulse_dirs_html = "".join(_dir_bars)
else:
    pulse_dirs_html = ""

if pulse_orgs:
    _max_org = max(c for _, c in pulse_orgs)
    _org_items = []
    for _name, _c in pulse_orgs:
        _w = int(_c / _max_org * 100)
        _q = html.escape(_name)
        _org_items.append(
            f'<div class="pulse-row" onclick="searchOrg(\'{_q}\')" title="查看 {_q} 的所有进展">'
            f'<span class="pulse-label">{html.escape(_name)}</span>'
            f'<span class="pulse-track"><span class="pulse-fill org-fill" style="width:{_w}%"></span></span>'
            f'<span class="pulse-num">{_c}</span></div>')
    pulse_orgs_html = "".join(_org_items)
else:
    pulse_orgs_html = ""

pulse_html = f"""
<div class="pulse-section">
  <div class="pulse-col">
    <h3>方向热度 <span class="pulse-hint">近 7 天论文</span></h3>
    {pulse_dirs_html}
  </div>
  <div class="pulse-col">
    <h3>机构活跃 <span class="pulse-hint">近 30 天一手 / 开源</span></h3>
    {pulse_orgs_html}
  </div>
</div>
<div class="trend-section">
  <h3>方向趋势 <span class="pulse-hint">近 12 周每周论文数，看哪个方向在升温</span></h3>
  <div class="trend-legend" id="trendLegend"></div>
  <svg id="trendChart" viewBox="0 0 760 220" preserveAspectRatio="xMidYMid meet" role="img"></svg>
</div>
"""

# ============ AI 方向综述（带引用的研究简报）============
briefing_path = PROJECT_ROOT / "data" / "briefing.json"
briefing_html = ""
if briefing_path.exists():
    bdata = json.load(open(briefing_path, encoding="utf-8"))
    briefings = bdata.get("briefings", [])

    def render_cite(pid):
        cp = papers_by_id.get(pid)
        if not cp:
            return ""
        title = cp.get("title", "")
        return (f'<a class="cite-chip" href="{cp.get("url","")}" target="_blank" '
                f'title="{html.escape(title)}">{html.escape(title[:42])}</a>')

    tabs, panels = [], []
    for i, b in enumerate(briefings):
        active = "active" if i == 0 else ""
        tabs.append(f'<button class="brief-tab {active}" onclick="switchBrief({i})">{html.escape(b["name"])}</button>')
        line_items = []
        for line in b.get("lines", []):
            cites = "".join([render_cite(pid) for pid in line.get("paper_ids", [])])
            line_items.append(
                f'<div class="brief-line">'
                f'<div class="brief-line-name">{html.escape(line.get("name",""))}</div>'
                f'<div class="brief-line-point">{html.escape(line.get("point",""))}</div>'
                f'<div class="brief-cites">{cites}</div></div>')
        trends = "".join([f'<li>{html.escape(t)}</li>' for t in b.get("trends", [])])
        panels.append(
            f'<div class="brief-panel {active}" data-i="{i}">'
            f'<div class="brief-overview">{html.escape(b.get("overview",""))}</div>'
            f'<div class="brief-lines">{"".join(line_items)}</div>'
            f'<div class="brief-trends"><b>趋势判断</b><ul>{trends}</ul></div>'
            f'</div>')
    briefing_html = (
        f'<div class="briefing-wrap"><div class="brief-tabs">{"".join(tabs)}</div>'
        f'<div class="brief-panels">{"".join(panels)}</div></div>')

# 本周热点
hot_tags_html = "".join([f'<span class="hot-tag">{t} ({c})</span>' for t, c in hot_tags_top])

# 本周必看 10 篇
def render_top_paper(p, rank):
    tags_html = "".join([f'<span class="tag">{html.escape(t)}</span>' for t in _public_tags(p.get("tags", []), limit=3)])
    authors_list = p.get("authors", [])
    authors = ", ".join(authors_list[:2])
    if len(authors_list) > 2:
        authors += " et al."
    if not authors:
        authors = p.get("source_name", "")

    # 来源徽章（学术/工业/媒体）
    source_type = p.get("source_type", "arxiv")
    source_name = p.get("source_name", "arXiv")
    if source_type in ("company_blog", "lab_blog"):
        source_badge = f'<span class="badge badge-industry">{html.escape(source_name)}</span>'
    elif source_type == "media":
        source_badge = f'<span class="badge badge-media">{html.escape(source_name)}</span>'
    elif source_type == "github":
        source_badge = '<span class="badge badge-github">开源</span>'
    elif source_type == "huggingface":
        source_badge = '<span class="badge badge-hf">模型</span>'
    else:
        source_badge = '<span class="badge badge-academic">学术</span>'

    gh_stars_span = ""
    if source_type == "github":
        rm = p.get("raw_metadata") or {}
        if rm.get("tag"):
            gh_stars_span = f'<span class="gh-stars">🏷️ {html.escape(str(rm["tag"]))}</span>'
        elif rm.get("stars") is not None:
            gh_stars_span = f'<span class="gh-stars">⭐ {rm["stars"]}</span>'
    elif source_type == "huggingface":
        rm = p.get("raw_metadata") or {}
        if rm.get("likes") is not None:
            gh_stars_span = f'<span class="hf-likes">🤍 {rm["likes"]}</span>'

    ai_summary = p.get("ai_summary")
    summary_html = ""
    if ai_summary:
        summary_html = f'''<div class="ai-summary"><span class="ai-badge">AI 速览</span><span class="ai-text">{html.escape(ai_summary)}</span></div>'''

    return f"""
    <div class="top-paper">
        <div class="rank">{rank}</div>
        <div class="top-paper-content">
            <div class="top-paper-title"><a href="{p['url']}" target="_blank">{html.escape(p['title'])}</a></div>
            <div class="top-paper-authors">{source_badge}<span class="top-paper-src">{html.escape(authors)}</span><span class="top-paper-date">{str(p['published_at'])[:10]}</span>{gh_stars_span}</div>
            <div class="top-paper-tags">{tags_html}</div>
            {summary_html}
        </div>
    </div>
    """

def _top_zone_divider(label):
    return f'<div class="top-zone-divider"><span>{label}</span></div>'

_top_parts = []
_rank = 1
_zone_labels = {"industry": "工业界 · 近 30 天重大发布",
                "opensource": "开源与模型 · 近 30 天热门项目 / 权重"}
for p in week_top:
    zone = p.get("_zone")
    if zone in _zone_labels and (not _top_parts or week_top[_rank - 2].get("_zone") != zone):
        _top_parts.append(_top_zone_divider(_zone_labels[zone]))
    _top_parts.append(render_top_paper(p, _rank))
    _rank += 1
week_top_html = "\n".join(_top_parts)

html_content = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>具身智能看板 - Embodied AI Dashboard</title>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background: #0a0c10;
            color: #e0e0e0;
            line-height: 1.6;
        }}
        .container {{ max-width: 1200px; margin: 0 auto; padding: 20px; }}
        header {{
            padding: 30px 0;
            border-bottom: 1px solid #222;
            margin-bottom: 30px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        h1 {{ font-size: 28px; color: #fff; }}
        .stats {{ color: #888; font-size: 14px; }}
        .since-banner {{
            display: flex; align-items: center; gap: 14px;
            margin: 14px 0 4px; padding: 11px 16px;
            background: linear-gradient(90deg, #1a1410, #16181d);
            border: 1px solid #7c2d12; border-radius: 10px;
        }}
        .since-text {{ color: #e8c9a8; font-size: 13px; flex: 1; }}
        .since-btn {{
            background: #7c2d12; color: #fdba74; border: none;
            padding: 7px 16px; border-radius: 8px; font-size: 13px; cursor: pointer;
        }}
        .since-btn:hover {{ background: #9a3412; }}
        .since-close {{ color: #8b94a3; cursor: pointer; font-size: 13px; padding: 0 4px; }}
        .header-tools {{ display: flex; align-items: center; gap: 12px; flex-shrink: 0; }}
        .rss-link {{
            color: #fdba74; font-size: 13px; text-decoration: none;
            padding: 6px 12px; border-radius: 20px;
            border: 1px solid #7c2d12;
        }}
        .rss-link:hover {{ background: #7c2d12; }}
        .rss-menu {{ position: relative; }}
        .rss-dropdown {{
            display: none; position: absolute; top: calc(100% + 8px); right: 0; z-index: 200;
            background: #1a1d24; border: 1px solid #2a313c; border-radius: 10px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.5); padding: 6px; min-width: 250px;
        }}
        .rss-menu:hover .rss-dropdown, .rss-menu:focus-within .rss-dropdown {{ display: block; }}
        .rss-dropdown a {{
            display: block; padding: 9px 12px; border-radius: 7px;
            color: #c9d3e0; font-size: 13px; text-decoration: none; white-space: nowrap;
        }}
        .rss-dropdown a:hover {{ background: #243044; color: #fff; }}
        .fav-count {{
            background: #7c2d12;
            color: #fdba74;
            padding: 6px 12px;
            border-radius: 20px;
            font-size: 13px;
            cursor: pointer;
            flex-shrink: 0;
        }}
        .stats-bar {{
            display: flex;
            gap: 25px;
            margin-top: 12px;
        }}
        .stat-item {{
            text-align: center;
        }}
        .stat-num {{
            font-size: 22px;
            font-weight: bold;
            color: #4da6ff;
        }}
        .stat-label {{
            font-size: 11px;
            color: #666;
        }}
        
        /* 布局 */
        .main-content {{
            display: grid;
            grid-template-columns: 200px 1fr;
            gap: 30px;
        }}
        
        /* 侧边栏 */
        .sidebar {{
            position: sticky;
            top: 20px;
        }}
        .sidebar h3 {{
            font-size: 14px;
            color: #888;
            margin-bottom: 15px;
            text-transform: uppercase;
        }}
        .sidebar-section {{
            margin-bottom: 25px;
        }}
        .sidebar-item {{
            padding: 8px 12px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 14px;
            color: #ccc;
            transition: all 0.2s;
        }}
        .sidebar-item:hover {{
            background: #1a1d23;
            color: #fff;
        }}
        .sidebar-item.active {{
            background: #1e293b;
            color: #93c5fd;
        }}
        
        /* 搜索 */
        .search-bar {{
            margin-bottom: 20px;
            position: relative;
        }}
        .search-bar input {{
            width: 100%;
            padding: 12px 45px 12px 16px;
            background: #1a1d23;
            border: 1px solid #333;
            border-radius: 8px;
            color: #e0e0e0;
            font-size: 14px;
        }}
        .search-hint {{
            position: absolute;
            right: 12px;
            top: 50%;
            transform: translateY(-50%);
            color: #555;
            font-size: 12px;
            background: #0a0c10;
            padding: 2px 8px;
            border-radius: 4px;
            border: 1px solid #222;
        }}
        
        /* 论文卡片 */
        .paper-card {{
            background: #14171d;
            border: 1px solid #222;
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 15px;
            transition: border-color 0.2s;
        }}
        .paper-card:hover {{ border-color: #444; }}
        .paper-card.favorited {{
            border-color: #7c2d12;
        }}
        .paper-header {{
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            margin-bottom: 8px;
        }}
        .paper-title {{ font-size: 16px; flex: 1; }}
        .paper-title a {{ color: #fff; text-decoration: none; }}
        .paper-title a:hover {{ color: #4da6ff; }}
        .fav-btn {{
            background: none;
            border: none;
            color: #666;
            font-size: 20px;
            cursor: pointer;
            margin-left: 10px;
            transition: color 0.2s;
        }}
        .fav-btn:hover {{ color: #fdba74; }}
        .fav-btn.favorited {{ color: #fdba74; }}
        .card-actions {{ display: flex; align-items: center; gap: 2px; margin-left: 10px; flex-shrink: 0; }}
        .read-btn {{
            background: none; border: none; color: #555; font-size: 15px;
            cursor: pointer; padding: 2px 4px; line-height: 1; transition: color 0.2s;
        }}
        .read-btn:hover {{ color: #7fb4e8; }}
        .read-btn.read {{ color: #4da6ff; }}
        /* 已读卡片淡化 */
        .paper-card.is-read {{ opacity: 0.55; }}
        .paper-card.is-read .paper-title a {{ color: #8a93a2; }}
        /* 阅读状态工具条 */
        .read-filter {{
            display: flex; align-items: center; gap: 8px;
            margin: 2px 0 16px; font-size: 12.5px;
        }}
        .rf-label {{ color: #6b7280; }}
        .rf-item {{
            padding: 3px 12px; border-radius: 14px; cursor: pointer;
            color: #aab4c0; background: #161a21; border: 1px solid #262b33;
            user-select: none;
        }}
        .rf-item:hover {{ border-color: #3a4350; color: #dce4ee; }}
        .rf-item.active {{ background: #1c2c40; border-color: #4da6ff; color: #7fb4e8; }}
        .rf-item b {{ color: #4da6ff; font-weight: 600; margin-left: 2px; }}
        .paper-authors {{ color: #888; font-size: 13px; }}
        .paper-meta {{
            display: flex;
            align-items: center;
            gap: 10px;
            flex-wrap: wrap;
            margin-bottom: 10px;
        }}
        .badge {{
            display: inline-block;
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 11px;
            font-weight: 500;
        }}
        .badge-academic {{
            background: #1e3a5f;
            color: #93c5fd;
        }}
        .badge-industry {{
            background: #7c2d12;
            color: #fdba74;
        }}
        .badge-media {{
            background: #365314;
            color: #bef264;
        }}
        .badge-github {{
            background: #134e4a;
            color: #5eead4;
        }}
        .badge-hf {{
            background: #831843;
            color: #f9a8d4;
        }}
        .gh-stars {{ color: #5eead4; font-size: 12px; margin-left: auto; }}
        .hf-likes {{ color: #f9a8d4; font-size: 12px; margin-left: auto; }}
        .gh-new {{
            background: #134e4a; color: #5eead4; font-size: 11px; font-weight: 600;
            padding: 1px 7px; border-radius: 4px;
        }}
        .hf-new {{
            background: #831843; color: #f9a8d4; font-size: 11px; font-weight: 600;
            padding: 1px 7px; border-radius: 4px;
        }}
        .paper-date {{ color: #666; font-size: 12px; }}
        .paper-tags {{ display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 10px; }}
        .tag {{
            background: #1e293b;
            color: #93c5fd;
            padding: 2px 8px;
            border-radius: 20px;
            font-size: 11px;
        }}
        .paper-abstract {{
            color: #888;
            font-size: 12px;
            line-height: 1.5;
            margin-bottom: 10px;
        }}
        mark {{
            background: #f59e0b;
            color: #000;
            padding: 0 2px;
            border-radius: 2px;
        }}
        .paper-links {{ font-size: 12px; }}
        .paper-links a {{
            color: #4da6ff;
            text-decoration: none;
            margin-right: 15px;
        }}
        .paper-links a:hover {{ text-decoration: underline; }}
        .res-link {{
            display: inline-flex; align-items: center; gap: 3px;
            padding: 2px 9px !important; border-radius: 6px; font-size: 11.5px !important;
            border: 1px solid transparent; text-decoration: none !important;
        }}
        .res-code {{ color: #7ee2a8 !important; background: rgba(63,185,80,0.10); border-color: rgba(63,185,80,0.28); }}
        .res-code:hover {{ background: rgba(63,185,80,0.18); }}
        .res-page {{ color: #7fb4e8 !important; background: rgba(77,166,255,0.10); border-color: rgba(77,166,255,0.28); }}
        .res-page:hover {{ background: rgba(77,166,255,0.18); }}
        .res-data {{ color: #d6a8f5 !important; background: rgba(190,120,220,0.10); border-color: rgba(190,120,220,0.28); }}
        .res-data:hover {{ background: rgba(190,120,220,0.18); }}

        /* 事件多源归并 */
        .event-sources {{
            margin: 8px 0 2px;
            padding: 8px 10px;
            background: rgba(77, 166, 255, 0.06);
            border: 1px solid rgba(77, 166, 255, 0.22);
            border-radius: 8px;
            font-size: 12px;
        }}
        .event-sources > summary {{
            cursor: pointer;
            color: #6fb4ff;
            font-weight: 600;
            list-style: none;
            user-select: none;
        }}
        .event-sources > summary::-webkit-details-marker {{ display: none; }}
        .event-sources > summary::before {{ content: "▸ "; }}
        .event-sources[open] > summary::before {{ content: "▾ "; }}
        .event-source-list {{
            margin-top: 8px;
            display: flex;
            flex-direction: column;
            gap: 6px;
        }}
        .event-source-link {{
            display: flex;
            align-items: center;
            gap: 8px;
            padding: 6px 8px;
            background: rgba(255,255,255,0.03);
            border-radius: 6px;
            text-decoration: none;
            color: #cfd6e0;
            line-height: 1.4;
        }}
        .event-source-link:hover {{ background: rgba(77,166,255,0.12); }}
        .es-tag {{
            flex: none;
            font-size: 11px;
            padding: 1px 7px;
            border-radius: 4px;
            font-weight: 600;
        }}
        .es-arxiv, .es-openreview, .es-huggingface, .es-github {{
            background: rgba(77,166,255,0.22); color: #9ecbff;
        }}
        .es-company_blog, .es-lab_blog, .es-x_thread {{
            background: rgba(255,159,67,0.2); color: #ffb27a;
        }}
        .es-media {{
            background: rgba(74,222,128,0.18); color: #7be0a0;
        }}
        .es-title {{ flex: none; font-weight: 600; max-width: 130px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
        .es-name {{ color: #9aa4b2; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}

        /* 重要进展（事件）专区 */
        /* 领域脉搏 */
        .pulse-section {{
            display: grid; grid-template-columns: 1fr 1fr; gap: 14px;
            margin-bottom: 24px;
        }}
        .pulse-col {{
            background: #14171d; border: 1px solid #222; border-radius: 12px;
            padding: 16px 18px;
        }}
        .pulse-col h3 {{ font-size: 14px; color: #fff; margin-bottom: 12px; }}
        .pulse-hint {{ font-size: 11px; color: #6b7280; font-weight: 400; margin-left: 8px; }}
        .pulse-row {{
            display: grid; grid-template-columns: 92px 1fr 34px; align-items: center;
            gap: 10px; padding: 3px 4px; border-radius: 6px; cursor: pointer;
        }}
        .pulse-row:hover {{ background: #1a1f27; }}
        .pulse-label {{ font-size: 12px; color: #c2c9d4; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
        .pulse-track {{ background: #1b2028; border-radius: 5px; height: 8px; overflow: hidden; }}
        .pulse-fill {{ display: block; height: 100%; background: linear-gradient(90deg,#2f6fb0,#4da6ff); border-radius: 5px; }}
        .pulse-fill.org-fill {{ background: linear-gradient(90deg,#134e4a,#5eead4); }}
        .pulse-num {{ font-size: 12px; color: #8a93a2; text-align: right; font-variant-numeric: tabular-nums; }}
        @media (max-width: 768px) {{ .pulse-section {{ grid-template-columns: 1fr; }} }}
        .trend-section {{
            background: #14171d; border: 1px solid #232a34; border-radius: 12px;
            padding: 16px 20px; margin-bottom: 30px;
        }}
        .trend-section h3 {{ margin: 0 0 12px; font-size: 15px; color: #e6eaf0; }}
        .trend-legend {{ display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 8px; }}
        .trend-legend-item {{ display: inline-flex; align-items: center; gap: 6px; font-size: 12px; color: #aab4c0; cursor: pointer; }}
        .trend-legend-dot {{ width: 10px; height: 3px; border-radius: 2px; display: inline-block; }}
        #trendChart {{ width: 100%; height: auto; display: block; }}
        .trend-line {{ fill: none; stroke-width: 2; }}
        .trend-dot {{ stroke: #14171d; stroke-width: 1.5; }}
        .trend-axis {{ stroke: #2a313c; stroke-width: 1; }}
        .trend-glabel {{ fill: #6b7280; font-size: 10px; }}
        .trend-ylabel {{ fill: #6b7280; font-size: 9px; text-anchor: end; }}
        .trend-section.off .trend-legend-item {{ opacity: 0.45; }}

        .events-section {{
            margin-bottom: 30px;
            padding: 20px;
            background: #14171d;
            border: 1px solid #222;
            border-radius: 12px;
        }}
        .events-section h2 {{ font-size: 16px; color: #fff; margin-bottom: 6px; }}
        .event-cards {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 14px; }}
        .event-card {{
            background: #101318;
            border: 1px solid #23272f;
            border-radius: 10px;
            padding: 13px 14px;
        }}
        .event-card:hover {{ border-color: #3a4350; }}
        .event-card-title {{ font-size: 14px; font-weight: 600; line-height: 1.35; margin-bottom: 9px; }}
        .event-card-title a {{ color: #e8edf3; }}
        .event-card-title a:hover {{ color: #4da6ff; }}
        .event-card-meta {{ display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 9px; }}
        .event-card-date {{ color: #8b94a3; font-size: 12px; }}
        .event-card-count {{ color: #9aa4b2; font-size: 12px; }}
        .event-card-sources {{ display: flex; flex-wrap: wrap; gap: 6px; }}
        .ev-src-link {{
            display: inline-flex; align-items: center; gap: 5px;
            font-size: 12px; color: #c2c9d4;
            padding: 3px 9px 3px 4px; border-radius: 6px;
            background: #171b21; border: 1px solid #262b33;
        }}
        .ev-src-link:hover {{ background: #1d232c; border-color: #3a4350; }}

        /* 事件 AI 解读 */
        .event-brief {{
            background: #10161f; border: 1px solid #1f2c3d; border-left: 3px solid #4da6ff;
            border-radius: 8px; padding: 9px 11px; margin-bottom: 10px;
        }}
        .eb-tldr {{ font-size: 12.5px; color: #dce4ee; line-height: 1.5; }}
        .eb-tldr .ai-badge {{ margin-right: 6px; }}
        .eb-more {{ margin-top: 6px; }}
        .eb-more summary {{ cursor: pointer; font-size: 11.5px; color: #7fb4e8; user-select: none; }}
        .eb-more summary:hover {{ color: #a9d0f5; }}
        .eb-what, .eb-why {{ font-size: 12px; color: #aab4c0; line-height: 1.55; margin-top: 6px; }}
        .eb-what b, .eb-why b {{ color: #8fb9e6; font-weight: 600; margin-right: 5px; }}

        /* AI 方向综述 */
        .briefing-section {{ margin-bottom: 30px; padding: 20px; background: #14171d; border: 1px solid #222; border-radius: 12px; }}
        .briefing-section h2 {{ font-size: 16px; color: #fff; margin-bottom: 14px; }}
        .brief-tabs {{ display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 16px; }}
        .brief-tab {{
            background: #171b21; border: 1px solid #262b33; color: #9aa4b2;
            padding: 7px 14px; border-radius: 8px; font-size: 13px; cursor: pointer;
        }}
        .brief-tab:hover {{ border-color: #3a4350; color: #c2c9d4; }}
        .brief-tab.active {{ background: #1c2735; border-color: #3a6ea5; color: #9ecbff; }}
        .brief-panel {{ display: none; }}
        .brief-panel.active {{ display: block; }}
        .brief-overview {{ color: #d4dae3; font-size: 13.5px; line-height: 1.7; margin-bottom: 16px; padding: 12px 14px; background: #101318; border-left: 3px solid #3a6ea5; border-radius: 6px; }}
        .brief-lines {{ display: flex; flex-direction: column; gap: 13px; margin-bottom: 16px; }}
        .brief-line-name {{ font-size: 13.5px; font-weight: 600; color: #e8edf3; margin-bottom: 5px; }}
        .brief-line-point {{ color: #aab2bd; font-size: 13px; line-height: 1.65; margin-bottom: 7px; }}
        .brief-cites {{ display: flex; flex-wrap: wrap; gap: 6px; }}
        .cite-chip {{
            font-size: 11.5px; color: #9ecbff; text-decoration: none;
            padding: 2px 9px; border-radius: 5px;
            background: rgba(77,166,255,0.1); border: 1px solid rgba(77,166,255,0.25);
        }}
        .cite-chip:hover {{ background: rgba(77,166,255,0.2); }}
        .brief-trends {{ background: #101318; border-radius: 8px; padding: 12px 14px; }}
        .brief-trends b {{ color: #e8edf3; font-size: 13px; }}
        .brief-trends ul {{ margin: 8px 0 0; padding-left: 18px; }}
        .brief-trends li {{ color: #c2c9d4; font-size: 13px; line-height: 1.7; }}

        /* 热点 */
        .hot-section {{
            margin-bottom: 30px;
            padding: 20px;
            background: #14171d;
            border: 1px solid #222;
            border-radius: 12px;
        }}
        .hot-section h2 {{
            font-size: 16px;
            color: #fff;
            margin-bottom: 15px;
        }}
        .hot-tag {{
            display: inline-block;
            background: #7c2d12;
            color: #fdba74;
            padding: 4px 10px;
            border-radius: 20px;
            font-size: 12px;
            margin-right: 8px;
            margin-bottom: 8px;
        }}
        
        /* 本周必看 */
        /* AI 本周导读（顶部执行摘要） */
        .intro-section {{
            margin-bottom: 24px; padding: 18px 20px;
            background: linear-gradient(135deg, #131c2b 0%, #14171d 60%);
            border: 1px solid #243246; border-radius: 12px;
            border-left: 3px solid #4da6ff;
        }}
        .intro-head {{ display: flex; align-items: baseline; gap: 10px; margin-bottom: 14px; flex-wrap: wrap; }}
        .intro-headline {{ font-size: 15.5px; font-weight: 600; color: #eef3f9; line-height: 1.5; }}
        .intro-items {{ display: grid; grid-template-columns: 1fr; gap: 10px; margin-bottom: 12px; }}
        .intro-item {{ background: rgba(255,255,255,0.025); border: 1px solid #232a34; border-radius: 8px; padding: 9px 12px; }}
        .intro-title {{ display: flex; align-items: baseline; gap: 8px; font-size: 13.5px; font-weight: 600; color: #cfe3f7; text-decoration: none; line-height: 1.4; }}
        .intro-title:hover {{ color: #7fb4e8; }}
        .intro-num {{
            flex: none; display: inline-flex; align-items: center; justify-content: center;
            width: 18px; height: 18px; border-radius: 50%; font-size: 11px; font-weight: 700;
            background: #1c3a55; color: #7fb4e8;
        }}
        .intro-why {{ font-size: 12.5px; color: #97a2b2; line-height: 1.5; margin-top: 4px; padding-left: 26px; }}
        .intro-trend {{ font-size: 12.5px; color: #aab4c0; line-height: 1.5; padding-top: 10px; border-top: 1px dashed #2a313c; }}
        .intro-trend-label {{
            display: inline-block; font-size: 11px; color: #f0c674; background: rgba(240,198,116,0.10);
            border: 1px solid rgba(240,198,116,0.28); border-radius: 5px; padding: 1px 7px; margin-right: 8px;
        }}

        .top-section {{
            margin-bottom: 30px;
            padding: 20px;
            background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
            border: 1px solid #334155;
            border-radius: 12px;
        }}
        .top-section h2 {{
            font-size: 18px;
            color: #fff;
            margin-bottom: 15px;
        }}
        .top-sub {{ font-size: 12px; color: #888; font-weight: 400; margin-left: 8px; }}
        .top-paper {{
            display: flex;
            align-items: flex-start;
            padding: 12px 0;
            border-bottom: 1px solid #1e293b;
        }}
        .top-paper:last-child {{ border-bottom: none; }}
        .rank {{
            width: 28px;
            height: 28px;
            background: #f59e0b;
            color: #000;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 14px;
            font-weight: bold;
            margin-right: 15px;
            flex-shrink: 0;
        }}
        .top-paper-content {{ flex: 1; }}
        .top-paper-title {{ font-size: 14px; margin-bottom: 4px; }}
        .top-paper-title a {{ color: #fff; text-decoration: none; }}
        .top-paper-title a:hover {{ color: #4da6ff; }}
        .top-paper-authors {{ color: #888; font-size: 12px; margin-bottom: 6px; display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }}
        .top-paper-src {{ color: #999; }}
        .top-paper-date {{ color: #666; margin-left: auto; }}
        .top-zone-divider {{
            margin: 16px 0 6px;
            padding-top: 12px;
            border-top: 1px dashed #2a2a2a;
            font-size: 12px;
            color: #ff9d4d;
            font-weight: 600;
            letter-spacing: 0.5px;
        }}
        .top-paper-tags {{ display: flex; gap: 4px; flex-wrap: wrap; }}
        .ai-summary {{
            margin-top: 10px;
            padding: 10px 12px;
            background: rgba(77, 166, 255, 0.08);
            border-left: 3px solid #4da6ff;
            border-radius: 0 6px 6px 0;
            font-size: 13px;
            line-height: 1.6;
            color: #c7d2e0;
        }}
        .ai-badge {{
            display: inline-block;
            background: #1e3a5f;
            color: #93c5fd;
            font-size: 10px;
            font-weight: 600;
            padding: 2px 7px;
            border-radius: 4px;
            margin-right: 8px;
            vertical-align: top;
            white-space: nowrap;
        }}
        .ai-text {{ color: #c7d2e0; }}
        
        /* 模态框 */
        .modal {{
            display: none;
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0,0,0,0.8);
            z-index: 1000;
        }}
        .modal-content {{
            position: absolute;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            background: #14171d;
            border: 1px solid #333;
            border-radius: 12px;
            padding: 30px;
            max-width: 600px;
            max-height: 80vh;
            overflow-y: auto;
        }}
        .modal-close {{
            position: absolute;
            top: 15px;
            right: 15px;
            background: none;
            border: none;
            color: #888;
            font-size: 24px;
            cursor: pointer;
        }}
        
        /* 移动端适配 */
        @media (max-width: 768px) {{
            .container {{ padding: 12px; }}
            header {{
                flex-direction: column;
                align-items: flex-start;
                gap: 12px;
                padding: 15px 0;
            }}
            h1 {{ font-size: 22px; }}
            .stats-bar {{ gap: 15px; flex-wrap: wrap; }}
            .stat-num {{ font-size: 18px; }}
            .main-content {{
                grid-template-columns: 1fr;
                gap: 15px;
            }}
            .event-cards {{ grid-template-columns: 1fr; }}
            .sidebar {{
                position: static;
                display: flex;
                gap: 15px;
                overflow-x: auto;
                padding-bottom: 10px;
            }}
            .sidebar-section {{
                margin-bottom: 0;
                flex-shrink: 0;
                min-width: 130px;
            }}
            .sidebar h3 {{ font-size: 12px; margin-bottom: 8px; }}
            .sidebar-item {{ font-size: 13px; padding: 6px 10px; white-space: nowrap; }}
            .paper-card {{ padding: 15px; }}
            .paper-title {{ font-size: 15px; }}
            .top-section, .hot-section {{ padding: 15px; }}
            .intro-section {{ padding: 14px 15px; }}
            .intro-headline {{ font-size: 14.5px; }}
            .intro-why {{ padding-left: 0; }}
            .read-filter {{ overflow-x: auto; flex-wrap: nowrap; -webkit-overflow-scrolling: touch; }}
            .rf-item {{ white-space: nowrap; flex-shrink: 0; }}
            .paper-links {{ flex-wrap: wrap; }}
            .modal-content {{ width: 90%; padding: 20px; }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div>
                <h1>具身智能看板</h1>
                <div class="stats-bar">
                    <div class="stat-item">
                        <div class="stat-num">{len(papers)}</div>
                        <div class="stat-label">90天论文</div>
                    </div>
                    <div class="stat-item">
                        <div class="stat-num">{len(week_papers)}</div>
                        <div class="stat-label">本周新增</div>
                    </div>
                    <div class="stat-item">
                        <div class="stat-num">{sum(1 for p in papers if p.get('has_real_robot', False))}</div>
                        <div class="stat-label">真机实验</div>
                    </div>
                    <div class="stat-item">
                        <div class="stat-num">{sum(1 for p in papers if p.get('is_open_source', False))}</div>
                        <div class="stat-label">已开源</div>
                    </div>
                </div>
            </div>
            <div class="header-tools">
                <div class="rss-menu">
                    <a class="rss-link" href="feed.xml" target="_blank" title="用 RSS 阅读器订阅重要进展">RSS 订阅 ▾</a>
                    <div class="rss-dropdown">
                        <a href="feed.xml" target="_blank">📌 全部重要进展（事件+精选）</a>
                        <a href="feed-vla.xml" target="_blank">🧠 VLA 视觉语言动作</a>
                        <a href="feed-world-model.xml" target="_blank">🌍 世界模型</a>
                        <a href="feed-industry.xml" target="_blank">🏭 工业界一手发布</a>
                    </div>
                </div>
                <div class="fav-count" onclick="showFavs()">收藏 (<span id="favCount">0</span>)</div>
            </div>
        </header>

        <div id="sinceBanner" class="since-banner" style="display:none">
            <span id="sinceText" class="since-text"></span>
            <button id="sinceBtn" class="since-btn">查看新进展</button>
            <span class="since-close" onclick="document.getElementById('sinceBanner').style.display='none'">✕</span>
        </div>

        <div class="main-content">
            <div class="sidebar">
                <div class="sidebar-section">
                    <h3>内容类型</h3>
                    <div class="sidebar-item active" onclick="filterBySource('')">全部</div>
                    <div class="sidebar-item" onclick="filterBySource('arxiv')">学术论文</div>
                    <div class="sidebar-item" onclick="filterBySource('industry')">工业界博客</div>
                    <div class="sidebar-item" onclick="filterBySource('media')">媒体</div>
                    <div class="sidebar-item" onclick="filterBySource('github')">开源项目</div>
                    <div class="sidebar-item" onclick="filterBySource('huggingface')">模型权重</div>
                </div>
                <div class="sidebar-section">
                    <h3>标签筛选</h3>
                    <div class="sidebar-item active" onclick="filterByTag('')">全部</div>
                    <div class="sidebar-item" onclick="filterByTag('VLA')">VLA</div>
                    <div class="sidebar-item" onclick="filterByTag('world_model')">世界模型</div>
                    <div class="sidebar-item" onclick="filterByTag('sim2real')">Sim2Real</div>
                    <div class="sidebar-item" onclick="filterByTag('diffusion_policy')">Diffusion Policy</div>
                    <div class="sidebar-item" onclick="filterByTag('foundation_model')">Foundation Model</div>
                </div>
                <div class="sidebar-section">
                    <h3>时间范围</h3>
                    <div class="sidebar-item active" onclick="filterByTime(0)">全部</div>
                    <div class="sidebar-item" onclick="filterByTime(1)">今天</div>
                    <div class="sidebar-item" onclick="filterByTime(7)">本周</div>
                    <div class="sidebar-item" onclick="filterByTime(30)">本月</div>
                </div>
                <div class="sidebar-section">
                    <h3>其他筛选</h3>
                    <div class="sidebar-item" onclick="filterByProperty('real', true)">有真机实验</div>
                    <div class="sidebar-item" onclick="filterByProperty('open', true)">已开源</div>
                </div>
                <div class="sidebar-section">
                    <h3>工具</h3>
                    <div class="sidebar-item" onclick="exportFavs()">导出收藏 (Markdown)</div>
                    <div class="sidebar-item" onclick="clearAllFilters()">清除所有筛选</div>
                </div>
            </div>
            
            <div class="content">
                <div class="search-bar">
                    <input type="text" id="search" placeholder="搜索标题、作者、摘要...（2000+篇）" oninput="onSearchInput()">
                    <span class="search-hint">按 / 快速搜索</span>
                </div>

                <div class="read-filter">
                    <span class="rf-label">阅读状态</span>
                    <span class="rf-item active" onclick="filterByRead('all')">全部</span>
                    <span class="rf-item" onclick="filterByRead('unread')">未读 <b id="unreadCount">0</b></span>
                    <span class="rf-item" onclick="filterByRead('read')">已读</span>
                </div>

                {intro_html}

                <div class="top-section">
                    <h2>本周必看 <span class="top-sub">学术前沿 7 + 工业界重大发布 3 + 开源/模型 3</span></h2>
                    <div class="top-papers">
                        {week_top_html}
                    </div>
                </div>

                {pulse_html}

                <div class="events-section">
                    <h2>重要进展 · 跨源全貌 <span class="top-sub">同一进展的论文 / 官方 / 媒体 / 开源 / 模型，一次看完</span></h2>
                    <div class="event-cards">
                        {events_html}
                    </div>
                </div>

                <div class="briefing-section">
                    <h2>AI 方向综述 <span class="top-sub">基于近 90 天论文自动生成，引用可溯源</span></h2>
                    {briefing_html}
                </div>

                <div class="hot-section">
                    <h2>本周热点</h2>
                    <div class="hot-tags">
                        {hot_tags_html}
                    </div>
                </div>
                
                <div id="papers">
                    {papers_html}
                </div>
                
                <div id="searchHint" style="display:none;margin:10px 0 4px;padding:8px 14px;background:rgba(240,198,116,0.08);border:1px solid rgba(240,198,116,0.25);border-radius:8px;color:#f0c674;font-size:12.5px"></div>

                <div id="emptyState" style="display:none;text-align:center;padding:60px 20px;color:#666">
                    <div style="font-size:48px;margin-bottom:15px">🔍</div>
                    <p id="emptyTitle" style="margin-bottom:10px">没有找到匹配的论文</p>
                    <p style="font-size:13px">试试换个关键词，或减少关键词、清除筛选条件</p>
                </div>

                <div id="loadMoreWrap" style="text-align:center;padding:25px 0 10px">
                    <div id="loadMoreInfo" style="color:#666;font-size:12px;margin-bottom:10px"></div>
                    <button id="loadMoreBtn" onclick="loadMore()" style="display:none;background:#1e293b;color:#e2e8f0;border:1px solid #334155;padding:10px 28px;border-radius:8px;font-size:14px;cursor:pointer"></button>
                </div>
            </div>
        </div>
    </div>
    
    <!-- 模态框 -->
    <div id="modal" class="modal">
        <div class="modal-content">
            <button class="modal-close" onclick="closeModal()">×</button>
            <div id="modalBody"></div>
        </div>
    </div>

    <script>
        let currentTag = '';
        let currentProperty = '';
        let currentPropertyValue = '';
        let currentTimeRange = 0;
        let currentSource = '';
        const PAGE_SIZE = 60;
        let renderLimit = PAGE_SIZE;
        let showOnlyFavs = false;
        let favorites = JSON.parse(localStorage.getItem('favorites') || '[]');
        
        function updateFavCount() {{
            document.getElementById('favCount').textContent = favorites.length;
        }}
        
        function copyBib(id) {{
            const card = document.querySelector(`[data-id="${{id}}"]`);
            if (!card || !card.dataset.bibtex) return;
            const text = card.dataset.bibtex;
            const modal = document.getElementById('modal');
            const body = document.getElementById('modalBody');
            body.innerHTML = `
                <h2 style="margin:0 0 12px;color:#fff">BibTeX 引用</h2>
                <textarea id="bibText" style="width:100%;height:230px;box-sizing:border-box;background:#0f1115;color:#cfe3ff;border:1px solid #2a313c;border-radius:8px;padding:12px;font-family:ui-monospace,Consolas,monospace;font-size:12px;line-height:1.6"></textarea>
                <div style="text-align:right;margin-top:12px">
                    <button onclick="closeModal()" style="background:transparent;color:#8a93a2;border:1px solid #334155;padding:8px 16px;border-radius:8px;margin-right:8px;cursor:pointer">关闭</button>
                    <button id="bibCopyBtn" style="background:#4da6ff;color:#fff;border:none;padding:8px 18px;border-radius:8px;cursor:pointer">复制到剪贴板</button>
                </div>`;
            const ta = document.getElementById('bibText');
            ta.value = text;
            const btn = document.getElementById('bibCopyBtn');
            const doCopy = () => {{
                ta.focus(); ta.select();
                let ok = false;
                try {{ ok = document.execCommand('copy'); }} catch (e) {{}}
                if (navigator.clipboard && navigator.clipboard.writeText) {{
                    navigator.clipboard.writeText(ta.value).then(
                        () => {{ btn.textContent = '已复制 ✓'; }},
                        () => {{ if (ok) btn.textContent = '已复制 ✓'; }});
                }} else if (ok) {{ btn.textContent = '已复制 ✓'; }}
            }};
            btn.onclick = doCopy;
            modal.style.display = 'flex';
            doCopy();
        }}

        function toggleFav(id) {{
            const idx = favorites.indexOf(id);
            if (idx > -1) {{
                favorites.splice(idx, 1);
            }} else {{
                favorites.push(id);
            }}
            localStorage.setItem('favorites', JSON.stringify(favorites));
            updateFavCount();
            updateFavButtons();
            filterPapers();
        }}
        
        function updateFavButtons() {{
            document.querySelectorAll('.paper-card').forEach(card => {{
                const id = card.dataset.id;
                const btn = card.querySelector('.fav-btn');
                if (favorites.includes(id)) {{
                    btn.classList.add('favorited');
                    btn.textContent = '★';
                    card.classList.add('favorited');
                }} else {{
                    btn.classList.remove('favorited');
                    btn.textContent = '☆';
                    card.classList.remove('favorited');
                }}
            }});
        }}

        // ===== 已读 / 未读追踪 =====
        let readItems = JSON.parse(localStorage.getItem('readItems') || '[]');
        let readFilter = 'all';   // all | unread | read

        function markRead(id) {{
            if (!readItems.includes(id)) {{
                readItems.push(id);
                localStorage.setItem('readItems', JSON.stringify(readItems));
                updateReadButtons();
                updateUnreadCount();
                if (readFilter !== 'all') filterPapers();
            }}
        }}

        function toggleRead(id) {{
            const idx = readItems.indexOf(id);
            if (idx > -1) readItems.splice(idx, 1);
            else readItems.push(id);
            localStorage.setItem('readItems', JSON.stringify(readItems));
            updateReadButtons();
            updateUnreadCount();
            filterPapers();
        }}

        function updateReadButtons() {{
            document.querySelectorAll('.paper-card').forEach(card => {{
                const btn = card.querySelector('.read-btn');
                if (!btn) return;
                if (readItems.includes(card.dataset.id)) {{
                    btn.classList.add('read');
                    btn.textContent = '●';
                    card.classList.add('is-read');
                }} else {{
                    btn.classList.remove('read');
                    btn.textContent = '◯';
                    card.classList.remove('is-read');
                }}
            }});
        }}

        function updateUnreadCount() {{
            const el = document.getElementById('unreadCount');
            if (!el) return;
            let n = 0;
            document.querySelectorAll('.paper-card').forEach(card => {{
                if (!readItems.includes(card.dataset.id)) n++;
            }});
            el.textContent = n;
        }}

        function filterByRead(mode) {{
            readFilter = mode;
            document.querySelectorAll('.read-filter .rf-item').forEach(i => i.classList.remove('active'));
            if (event.target.classList.contains('rf-item')) event.target.classList.add('active');
            resetPagination();
            filterPapers();
        }}
        
        function showFavs() {{
            showOnlyFavs = !showOnlyFavs;
            resetPagination();
            filterPapers();
        }}
        
        function filterPapers() {{
            const search = document.getElementById('search').value.trim();
            const terms = search.toLowerCase().split(/\s+/).filter(Boolean);
            const cards = document.querySelectorAll('.paper-card');
            let matchedCount = 0;
            let shownCount = 0;

            // 搜索匹配：多词默认 AND；AND 无结果时自动降级为 OR 并提示（避免"一搜就空"）
            let searchMode = 'and';
            const hayOf = card =>
                (card.querySelector('.paper-title').textContent + ' ' +
                 card.querySelector('.paper-authors').textContent + ' ' +
                 card.querySelector('.paper-abstract').textContent + ' ' +
                 (card.dataset.tags || '')).toLowerCase();
            if (terms.length) {{
                let andCount = 0;
                cards.forEach(card => {{ if (terms.every(t => hayOf(card).includes(t))) andCount++; }});
                if (andCount === 0) searchMode = 'or';
            }}
            const matchTerms = hay =>
                terms.length === 0 ? true :
                (searchMode === 'and' ? terms.every(t => hay.includes(t))
                                      : terms.some(t => hay.includes(t)));

            cards.forEach(card => {{
                const titleEl = card.querySelector('.paper-title');
                const authorsEl = card.querySelector('.paper-authors');
                const abstractEl = card.querySelector('.paper-abstract');
                const tags = card.dataset.tags || '';

                const title = titleEl.textContent.toLowerCase();
                const authors = authorsEl.textContent.toLowerCase();
                const abstract = abstractEl.textContent.toLowerCase();
                const hay = title + ' ' + authors + ' ' + abstract + ' ' + tags;

                const matchSearch = matchTerms(hay);
                const matchTag = !currentTag || tags.includes(currentTag);
                
                let matchProperty = true;
                if (currentProperty) {{
                    matchProperty = card.dataset[currentProperty] === currentPropertyValue;
                }}
                
                let matchFav = true;
                if (showOnlyFavs) {{
                    matchFav = favorites.includes(card.dataset.id);
                }}
                
                let matchTime = true;
                if (currentTimeRange > 0) {{
                    const cutoff = new Date();
                    cutoff.setDate(cutoff.getDate() - currentTimeRange);
                    const paperDate = new Date(card.dataset.date);
                    matchTime = paperDate >= cutoff;
                }}
                
                let matchSource = !currentSource || card.dataset.source === currentSource;

                // 已读筛选
                let matchRead = true;
                if (readFilter === 'unread') matchRead = !readItems.includes(card.dataset.id);
                else if (readFilter === 'read') matchRead = readItems.includes(card.dataset.id);

                // 事件聚合：全览（无任何筛选）时，同一事件只显示主卡片，其余来源折叠隐藏；
                // 一旦用户搜索/筛选，就允许命中具体来源（如媒体报道）本身
                const browsingAll = !search && !currentTag && !currentProperty &&
                    !showOnlyFavs && currentTimeRange === 0 && !currentSource &&
                    readFilter === 'all';
                const matchDup = !(browsingAll && card.dataset.eventDup === '1');

                const matched = matchSearch && matchTag && matchProperty && matchFav &&
                    matchTime && matchSource && matchRead && matchDup;
                if (matched) {{
                    matchedCount++;
                    // 分页：只显示前 renderLimit 个匹配项
                    if (matchedCount <= renderLimit) {{
                        card.style.display = 'block';
                        shownCount++;
                    }} else {{
                        card.style.display = 'none';
                    }}
                }} else {{
                    card.style.display = 'none';
                }}
                
                // 搜索高亮
                if (terms.length && matched && shownCount >= 0 && card.style.display === 'block') {{
                    highlightText(titleEl, terms);
                    highlightText(abstractEl, terms);
                }} else {{
                    // 恢复原文
                    if (card.dataset.originalTitle) {{
                        titleEl.innerHTML = card.dataset.originalTitle;
                    }}
                    if (card.dataset.originalAbstract) {{
                        abstractEl.innerHTML = card.dataset.originalAbstract;
                    }}
                }}
            }});
            
            // 空状态 + 放宽匹配提示
            const emptyState = document.getElementById('emptyState');
            const searchHint = document.getElementById('searchHint');
            if (matchedCount === 0) {{
                emptyState.style.display = 'block';
                document.getElementById('emptyTitle').textContent =
                    terms.length ? `没有找到与 “${{search}}” 匹配的结果` : '没有找到匹配的论文';
            }} else {{
                emptyState.style.display = 'none';
            }}
            if (terms.length && searchMode === 'or') {{
                searchHint.style.display = 'block';
                searchHint.textContent = `未找到同时包含所有词的结果，已放宽为匹配任意一个词（${{terms.join(' / ')}}）`;
            }} else {{
                searchHint.style.display = 'none';
            }}

            // 加载更多按钮
            updateLoadMore(matchedCount, shownCount);
        }}

        function updateLoadMore(matched, shown) {{
            const btn = document.getElementById('loadMoreBtn');
            const info = document.getElementById('loadMoreInfo');
            if (!btn) return;
            if (matched > shown) {{
                btn.style.display = 'block';
                const next = Math.min(PAGE_SIZE, matched - shown);
                btn.textContent = `加载更多（还有 ${{matched - shown}} 篇，显示 ${{next}} 篇）`;
                info.textContent = `共 ${{matched}} 篇，已显示 ${{shown}} 篇`;
            }} else {{
                btn.style.display = 'none';
                info.textContent = matched > 0 ? `共 ${{matched}} 篇，已全部显示` : '';
            }}
        }}

        function loadMore() {{
            renderLimit += PAGE_SIZE;
            filterPapers();
            window.scrollBy({{ top: 200, behavior: 'smooth' }});
        }}
        
        function highlightText(el, termsOrKeyword) {{
            if (!el.dataset.originalHtml) {{
                el.dataset.originalHtml = el.innerHTML;
            }}
            const original = el.dataset.originalHtml;
            const words = Array.isArray(termsOrKeyword) ? termsOrKeyword
                                                        : [termsOrKeyword];
            const special = '.^$*+?()|[]\\\\';
            let html = original;
            words.forEach(w => {{
                if (!w) return;
                let escaped = '';
                for (const ch of w) {{
                    escaped += special.includes(ch) ? '\\\\' + ch : ch;
                }}
                html = html.replace(new RegExp('(' + escaped + ')', 'gi'),
                    m => '<mark>' + m + '</mark>');
            }});
            el.innerHTML = html;
        }}
        
        function showOnboarding() {{
            if (localStorage.getItem('onboarded')) return;
            const modal = document.getElementById('modal');
            const body = document.getElementById('modalBody');
            body.innerHTML = `
                <h2 style="margin-bottom:20px;color:#fff">👋 欢迎使用具身智能看板</h2>
                <div style="color:#ccc;font-size:14px;line-height:1.8">
                    <p style="margin-bottom:15px">这个工具帮你<b>少读 80% 垃圾</b>，5 分钟看完本周关键进展。</p>
                    <p style="margin-bottom:10px"><b>📌 怎么用：</b></p>
                    <ul style="margin-left:20px;margin-bottom:15px">
                        <li>顶部：<b>本周必看 10 篇</b>（按重要性排序）</li>
                        <li>左侧：按标签筛选（VLA / 世界模型 / 仿真器）</li>
                        <li>搜索框：全文搜索标题、作者、摘要</li>
                        <li>点击 ☆ 收藏论文，刷新不丢失</li>
                        <li>点击"相关论文"看同方向的其他工作</li>
                    </ul>
                    <p style="margin-bottom:15px">聚焦三个方向：<b>VLA / 世界模型 / 仿真器</b></p>
                    <button onclick="closeModal();localStorage.setItem('onboarded','1');" 
                        style="background:#4da6ff;color:#fff;border:none;padding:10px 20px;border-radius:8px;cursor:pointer;font-size:14px">
                        开始使用
                    </button>
                </div>
            `;
            modal.style.display = 'block';
        }}
        
        function resetPagination() {{
            renderLimit = PAGE_SIZE;
        }}

        function onSearchInput() {{
            resetPagination();
            filterPapers();
        }}

        function filterByTag(tag) {{
            currentTag = tag;
            resetPagination();
            document.querySelectorAll('.sidebar-item').forEach(item => item.classList.remove('active'));
            event.target.classList.add('active');
            filterPapers();
        }}
        
        function filterBySource(source) {{
            currentSource = source;
            resetPagination();
            document.querySelectorAll('.sidebar-item').forEach(item => item.classList.remove('active'));
            event.target.classList.add('active');
            filterPapers();
        }}

        function searchOrg(name) {{
            // 机构脉搏：点击机构名 -> 全文搜索该机构，并重置来源/标签筛选
            currentTag = ''; currentSource = ''; currentProperty = null;
            showOnlyFavs = false; currentTimeRange = 0;
            readFilter = 'all';
            document.getElementById('search').value = name;
            resetPagination();
            filterPapers();
            document.getElementById('papers').scrollIntoView({{block:'start'}});
            window.scrollBy(0, -60);
        }}

        // ===== 方向趋势图（纯 SVG 折线）=====
        const TREND_DATA = {trend_series_json};
        const TREND_WLABELS = {trend_labels_json};
        const TREND_COLORS = {{'VLA':'#4da6ff','世界模型':'#f0c674','人形':'#5eead4','Sim2Real':'#c084fc'}};
        const trendHidden = new Set();
        function drawTrendChart() {{
            const svg = document.getElementById('trendChart');
            if (!svg) return;
            const W = 760, H = 220, L = 36, R = 14, T = 12, B = 24;
            const iw = W - L - R, ih = H - T - B;
            const n = TREND_WLABELS.length;
            const active = TREND_DATA.filter(s => !trendHidden.has(s.name));
            let maxV = 0;
            active.forEach(s => s.data.forEach(v => {{ if (v > maxV) maxV = v; }}));
            if (maxV === 0) maxV = 1;
            maxV = Math.ceil(maxV / 10) * 10 || 10;
            const X = i => L + (n === 1 ? 0 : i * iw / (n - 1));
            const Y = v => T + ih - (v / maxV) * ih;
            let html = '';
            // 水平网格 + y 刻度
            for (let g = 0; g <= 4; g++) {{
                const yv = Math.round(maxV * g / 4);
                const y = Y(yv);
                html += `<line class="trend-axis" x1="${{L}}" y1="${{y}}" x2="${{W-R}}" y2="${{y}}" opacity="0.5"/>`;
                html += `<text class="trend-ylabel" x="${{L-5}}" y="${{y+3}}">${{yv}}</text>`;
            }}
            // x 标签（首、中、末）
            [0, Math.floor((n-1)/2), n-1].forEach(i => {{
                html += `<text class="trend-glabel" x="${{X(i)}}" y="${{H-6}}" text-anchor="middle">${{TREND_WLABELS[i]}}</text>`;
            }});
            // 折线
            active.forEach(s => {{
                const c = TREND_COLORS[s.name] || '#888';
                const pts = s.data.map((v,i) => `${{X(i)}},${{Y(v)}}`).join(' ');
                html += `<polyline class="trend-line" stroke="${{c}}" points="${{pts}}"/>`;
                s.data.forEach((v,i) => {{
                    html += `<circle class="trend-dot" cx="${{X(i)}}" cy="${{Y(v)}}" r="2.6" fill="${{c}}"><title>${{s.name}} · ${{TREND_WLABELS[i]}}：${{v}} 篇</title></circle>`;
                }});
            }});
            svg.innerHTML = html;
            // 图例
            const lg = document.getElementById('trendLegend');
            lg.innerHTML = TREND_DATA.map(s => {{
                const c = TREND_COLORS[s.name] || '#888';
                const last = s.data[s.data.length-1], prev = s.data[s.data.length-2] || last;
                const arrow = last > prev ? '↑' : (last < prev ? '↓' : '→');
                const ac = last > prev ? '#5eead4' : (last < prev ? '#f87171' : '#8a93a2');
                return `<span class="trend-legend-item" data-name="${{s.name}}" style="${{trendHidden.has(s.name)?'opacity:.4':''}}">
                    <span class="trend-legend-dot" style="background:${{c}}"></span>${{s.name}}
                    <span style="color:${{ac}};font-variant-numeric:tabular-nums">${{last}} ${{arrow}}</span></span>`;
            }}).join('');
            lg.querySelectorAll('.trend-legend-item').forEach(el => el.addEventListener('click', () => {{
                const name = el.dataset.name;
                if (trendHidden.has(name)) trendHidden.delete(name); else trendHidden.add(name);
                lg.classList.add('off'); drawTrendChart();
            }}));
        }}
        
        function filterByProperty(property, value) {{
            currentProperty = property;
            currentPropertyValue = value ? 'true' : 'false';
            resetPagination();
            filterPapers();
        }}
        
        function filterByTime(days) {{
            currentTimeRange = days;
            resetPagination();
            document.querySelectorAll('.sidebar-item').forEach(item => item.classList.remove('active'));
            event.target.classList.add('active');
            filterPapers();
        }}
        
        function clearAllFilters() {{
            currentTag = '';
            currentProperty = '';
            currentPropertyValue = '';
            currentTimeRange = 0;
            currentSource = '';
            showOnlyFavs = false;
            readFilter = 'all';
            document.getElementById('search').value = '';
            document.querySelectorAll('.sidebar-item').forEach(item => item.classList.remove('active'));
            document.querySelectorAll('.rf-item').forEach(item => item.classList.remove('active'));
            document.querySelector('.sidebar-item').classList.add('active');
            resetPagination();
            filterPapers();
        }}
        
        function exportFavs() {{
            if (favorites.length === 0) {{
                alert('还没有收藏的论文');
                return;
            }}
            
            let md = '# 我的收藏 - 具身智能看板\\n\\n';
            const cards = document.querySelectorAll('.paper-card');
            let count = 0;
            
            cards.forEach(card => {{
                if (favorites.includes(card.dataset.id)) {{
                    count++;
                    const title = card.querySelector('.paper-title a').textContent;
                    const url = card.querySelector('.paper-title a').href;
                    const authors = card.querySelector('.paper-authors').textContent;
                    const tags = card.dataset.tags;
                    md += `## ${{count}}. ${{title}}\\n\\n`;
                    md += `- **作者**: ${{authors}}\\n`;
                    md += `- **标签**: ${{tags}}\\n`;
                    md += `- **链接**: ${{url}}\\n\\n`;
                }}
            }});
            
            const blob = new Blob([md], {{ type: 'text/markdown' }});
            const a = document.createElement('a');
            a.href = URL.createObjectURL(blob);
            a.download = `favorites_${{new Date().toISOString().slice(0,10)}}.md`;
            a.click();
        }}
        
        // 键盘快捷键
        document.addEventListener('keydown', (e) => {{
            // 按 / 聚焦搜索
            if (e.key === '/' && document.activeElement.id !== 'search') {{
                e.preventDefault();
                document.getElementById('search').focus();
            }}
            // ESC 关闭模态框
            if (e.key === 'Escape') {{
                closeModal();
            }}
        }});
        
        function showRelated(id) {{
            const card = document.querySelector(`[data-id="${{id}}"]`);
            if (!card) return;
            const tags = card.dataset.tags ? card.dataset.tags.split(' ').filter(Boolean) : [];
            const myEvent = card.dataset.eventId || '';
            const title = card.querySelector('.paper-title').textContent;
            const STOP = new Set(['robot','robots','robotics','learning','based','using','model','models',
                'data','with','from','for','via','toward','towards','policy','policies','vision','language',
                'action','actions','embodied','embodiment','image','images','novel','efficient','task','tasks']);
            const titleTokens = t => (t.toLowerCase().match(/[a-z][a-z0-9-]{{4,}}/g) || [])
                .filter(w => !STOP.has(w));
            const myWords = titleTokens(title);
            const related = [];

            document.querySelectorAll('.paper-card').forEach(c => {{
                if (c.dataset.id === id) return;
                const cTags = c.dataset.tags ? c.dataset.tags.split(' ').filter(Boolean) : [];
                let score = 0;
                // 同事件（同一工作的多源报道）最高优先
                if (myEvent && c.dataset.eventId === myEvent) score += 100;
                // 标签重叠
                const overlap = tags.filter(t => cTags.includes(t)).length;
                score += overlap * 4;
                // 标题共享稀有词
                const cWords = titleTokens(c.querySelector('.paper-title').textContent);
                let wordHit = 0;
                cWords.forEach(w => {{ if (myWords.includes(w)) wordHit++; }});
                score += wordHit * 3;
                // 时间相近（同一年）
                if (c.dataset.date && card.dataset.date &&
                    c.dataset.date.slice(0,4) === card.dataset.date.slice(0,4)) score += 1;
                if (score >= 4) {{
                    related.push({{
                        title: c.querySelector('.paper-title').textContent,
                        url: c.querySelector('.paper-title a').href,
                        score, overlap, sameEvent: score >= 100,
                        date: c.dataset.date,
                        source: c.querySelector('.source-badge') ? c.querySelector('.source-badge').textContent : ''
                    }});
                }}
            }});

            related.sort((a, b) => b.score - a.score);
            const modal = document.getElementById('modal');
            const body = document.getElementById('modalBody');
            const commonTags = t => t;
            body.innerHTML = '<h2 style="margin:0 0 6px;color:#fff">相关论文 / 进展</h2>' +
                '<div style="color:#8b94a3;font-size:12.5px;margin-bottom:16px">按同事件、标题主题与方向标签综合排序</div>' +
                (related.length === 0
                    ? '<div style="color:#8b94a3">暂无足够相关的条目，试试用方向标签筛选。</div>'
                    : related.slice(0, 12).map(r =>
                        `<div style="margin-bottom:13px;padding-left:10px;border-left:2px solid ${{r.sameEvent?'#4da6ff':'#2a313c'}}">
                            <a href="${{r.url}}" target="_blank" style="color:#cfe3f7;text-decoration:none;font-size:13.5px;line-height:1.5">${{r.title}}</a>
                            <div style="font-size:11.5px;color:#6b7280;margin-top:3px">
                                ${{r.sameEvent?'<span style="color:#4da6ff">同一事件</span> · ':''}}${{r.overlap>0?r.overlap+' 个共同标签':''}}${{r.date?' · '+r.date:''}}
                            </div>
                        </div>`
                    ).join(''));
            modal.style.display = 'block';
        }}
        
        function closeModal() {{
            document.getElementById('modal').style.display = 'none';
        }}
        
        // AI 方向综述切换
        function switchBrief(i) {{
            document.querySelectorAll('.brief-tab').forEach(function(t,idx){{
                t.classList.toggle('active', idx===i);
            }});
            document.querySelectorAll('.brief-panel').forEach(function(p){{
                p.classList.toggle('active', p.getAttribute('data-i') === String(i));
            }});
        }}

        // 自上次访问以来（localStorage 记录，纯前端轻量推送）
        function initSinceVisit() {{
            var now = new Date();
            var last = localStorage.getItem('lastVisit');
            localStorage.setItem('lastVisit', now.toISOString());
            if (!last) return;
            var lastDate = new Date(last);
            var cutoff = lastDate.toISOString().slice(0,10);
            var days = Math.floor((now - lastDate) / 86400000);
            var dayText = days <= 0 ? '今天' : days + ' 天前';
            // 优先统计新事件（跨源全貌）；其次统计一手/媒体新内容
            var newEvents = 0;
            document.querySelectorAll('.event-card').forEach(function(c){{
                if ((c.getAttribute('data-date')||'') >= cutoff) newEvents++;
            }});
            var newSrc = 0;
            document.querySelectorAll('.paper-card').forEach(function(c){{
                if (c.getAttribute('data-source') !== 'arxiv'
                    && (c.getAttribute('data-date')||'') >= cutoff) newSrc++;
            }});
            if (newEvents === 0 && newSrc === 0) return;
            var msg = '自上次访问（' + dayText + '）以来：';
            if (newEvents > 0) msg += newEvents + ' 个重要新进展';
            if (newSrc > 0) msg += (newEvents>0?'，':'') + newSrc + ' 篇官方/媒体更新';
            document.getElementById('sinceText').textContent = msg;
            document.getElementById('sinceBanner').style.display = 'flex';
            document.getElementById('sinceBtn').onclick = function() {{
                document.getElementById('sinceBanner').style.display = 'none';
                var target = newEvents > 0 ? '.events-section' : '#papers';
                window.scrollTo(0, document.querySelector(target).offsetTop - 20);
            }};
        }}

        // 初始化
        updateFavCount();
        updateFavButtons();
        updateReadButtons();
        updateUnreadCount();
        filterPapers();
        showOnboarding();
        initSinceVisit();
        drawTrendChart();
    </script>
</body>
</html>
"""

# 保存
out_dir = PROJECT_ROOT / "output"
out_dir.mkdir(exist_ok=True)
out_file = out_dir / "index.html"
with open(out_file, "w", encoding="utf-8") as f:
    f.write(html_content)

print(f"生成: {out_file}")
print(f"论文数: {len(papers)}")

# ============ 生成 RSS 订阅源（事件 + 精选，免费、无需服务器的推送能力）============
from email.utils import formatdate as _formatdate

def _rfc822(date_str):
    try:
        d = datetime.strptime(str(date_str)[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        return _formatdate(d.timestamp())
    except Exception:
        return _formatdate()

def _esc(s):
    return html.escape(str(s or ""), quote=True)

def _feed_item(guid, title, link, pub_date, desc_html):
    return f'''    <item>
      <title>{_esc(title)}</title>
      <link>{_esc(link)}</link>
      <description><![CDATA[{desc_html}]]></description>
      <pubDate>{_rfc822(pub_date)}</pubDate>
      <guid isPermaLink="false">{_esc(guid)}</guid>
    </item>'''

feed_items = []
_event_primary_ids = set()

# 1) 重要进展事件（每个事件一条，描述含全部来源链接）
for ev in recent_events:
    primary = papers_by_id.get(ev["primary"])
    if not primary:
        continue
    _event_primary_ids.add(ev["primary"])
    src_li = []
    for mid in ev["members"]:
        mp = papers_by_id.get(mid)
        if mp:
            src_li.append(
                f'<li>[{SOURCE_LABEL.get(mp.get("source_type"),"?")}] '
                f'<a href="{_esc(mp.get("url"))}">{_esc(mp.get("source_name"))}</a></li>'
            )
    desc = f'{ev["size"]} 个来源（论文 / 官方 / 媒体）：<ul>{"".join(src_li)}</ul>'
    feed_items.append(_feed_item(
        "event:" + ev["primary"], primary.get("title"),
        primary.get("url"), primary.get("published_at"), desc))

# 2) 本周必看精选（与事件主条目去重）
for p in week_top:
    if p["id"] in _event_primary_ids:
        continue
    ab = (p.get("abstract", "") or "")[:300]
    feed_items.append(_feed_item(
        "pick:" + p["id"], p.get("title"), p.get("url"),
        p.get("published_at"), _esc(ab)))

def _write_feed(filename, title, desc, items):
    body = "\n".join(items)
    xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>{_esc(title)}</title>
    <link>https://github.com/embodied-dashboard</link>
    <description>{_esc(desc)}</description>
    <language>zh-CN</language>
    <lastBuildDate>{_formatdate()}</lastBuildDate>
{body}
  </channel>
</rss>
'''
    path = out_dir / filename
    with open(path, "w", encoding="utf-8") as f:
        f.write(xml)
    print(f"生成: {path} ({len(items)} 条)")

# 主 feed：重要进展事件 + 本周必看精选
_write_feed(
    "feed.xml",
    "Embodied AI / VLA Dashboard — 重要进展",
    "具身智能 / VLA / 世界模型 / 仿真方向的跨源事件与精选，自动聚合论文、官方、媒体。",
    feed_items,
)

# 方向级 feed：研究者可只订阅自己关心的方向（近 30 天高分内容）
def _tag_feed(filename, tag, title, desc, limit=30):
    d = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    pool = [p for p in papers if tag in p.get("tags", []) and p.get("published_at", "")[:10] >= d]
    for p in pool:
        p["_fscore"] = calc_score(p)
    pool = sorted(pool, key=lambda x: x["_fscore"], reverse=True)[:limit]
    items = [_feed_item(p["id"], p.get("title"), p.get("url"), p.get("published_at"),
                        _esc((p.get("abstract", "") or "")[:300])) for p in pool]
    _write_feed(filename, title, desc, items)

_tag_feed("feed-vla.xml", "VLA", "Embodied AI — VLA（视觉语言动作）方向",
          "视觉语言动作模型（VLA）方向的最新论文与进展。")
_tag_feed("feed-world-model.xml", "world_model", "Embodied AI — 世界模型方向",
          "机器人 / 具身世界模型（World Model）方向的最新论文与进展。")

# 工业界一手发布 feed（公司 / 实验室官方博客）
_ind_d = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
_ind = [p for p in papers if p.get("source_type") in ("company_blog", "lab_blog")
        and p.get("published_at", "")[:10] >= _ind_d]
for p in _ind:
    p["_fscore"] = calc_industry_score(p)
_ind = sorted(_ind, key=lambda x: x["_fscore"], reverse=True)[:30]
_ind_items = [_feed_item(p["id"], p.get("title"), p.get("url"), p.get("published_at"),
                         _esc((p.get("abstract", "") or "")[:300])) for p in _ind]
_write_feed("feed-industry.xml", "Embodied AI — 工业界一手发布",
            "机器人公司与重点实验室的官方技术发布与开源动态。", _ind_items)


