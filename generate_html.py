"""
生成静态 HTML 展示页 v4
增加：收藏功能、相关论文推荐、更好的交互
"""
import json
import html
from pathlib import Path
from collections import Counter
from datetime import datetime, timedelta

PROJECT_ROOT = Path(__file__).parent

# 读取数据
with open(PROJECT_ROOT / "data" / "backfill" / "arxiv_backfill_90d_20261022.json", "r", encoding="utf-8") as f:
    papers = json.load(f)

# 按时间倒序
papers.sort(key=lambda p: p["published_at"], reverse=True)

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
def calc_score(p):
    score = 0
    # 标签权重：VLA、world_model、sim2real 是重点
    weight_map = {
        "VLA": 10,
        "world_model": 8,
        "sim2real": 7,
        "diffusion_policy": 6,
        "foundation_model": 6,
        "manipulation": 4,
        "locomotion": 3,
        "navigation": 3,
    }
    for t in p.get("tags", []):
        score += weight_map.get(t, 1)
    # 有真机实验加分
    if p.get("has_real_robot", False):
        score += 5
    # 已开源加分
    if p.get("is_open_source", False):
        score += 3
    # 作者数量（多人合作通常更重要）
    score += min(len(p.get("authors", [])), 5)
    return score

# 给本周论文打分
for p in week_papers:
    p["score"] = calc_score(p)

# 按分数排序，取前 10
week_top = sorted(week_papers, key=lambda x: x["score"], reverse=True)[:10]

# 生成论文卡片
def render_paper(p):
    tags_html = "".join([f'<span class="tag">{html.escape(t)}</span>' for t in p["tags"][:5]])
    authors = ", ".join(p["authors"][:3])
    if len(p["authors"]) > 3:
        authors += f" et al."
    
    # 摘要
    abstract = html.escape(p.get("abstract", "")[:150] + "..." if len(p.get("abstract", "")) > 150 else p.get("abstract", ""))
    
    # 标签数据
    tags_data = " ".join(p["tags"])
    has_real = "true" if p.get("has_real_robot", False) else "false"
    has_open = "true" if p.get("is_open_source", False) else "false"
    
    # 论文 ID（用于收藏）
    paper_id = p["id"].replace("/", "_")
    
    return f"""
    <div class="paper-card" data-id="{paper_id}" data-tags="{html.escape(tags_data)}" data-real="{has_real}" data-open="{has_open}" data-date="{p['published_at'][:10]}">
        <div class="paper-header">
            <div class="paper-title"><a href="{p['url']}" target="_blank">{html.escape(p['title'])}</a></div>
            <button class="fav-btn" onclick="toggleFav('{paper_id}')">☆</button>
        </div>
        <div class="paper-authors">{html.escape(authors)}</div>
        <div class="paper-date">{p['published_at'][:10]}</div>
        <div class="paper-tags">{tags_html}</div>
        <div class="paper-abstract">{abstract}</div>
        <div class="paper-links">
            <a href="{p['url']}" target="_blank">arXiv</a>
            <a href="javascript:void(0)" onclick="showRelated('{paper_id}')">相关论文</a>
        </div>
    </div>
    """

papers_html = "\n".join([render_paper(p) for p in papers[:200]])

# 本周热点
hot_tags_html = "".join([f'<span class="hot-tag">{t} ({c})</span>' for t, c in hot_tags_top])

# 本周必看 10 篇
def render_top_paper(p, rank):
    tags_html = "".join([f'<span class="tag">{html.escape(t)}</span>' for t in p["tags"][:3]])
    authors = ", ".join(p["authors"][:2])
    if len(p["authors"]) > 2:
        authors += f" et al."
    return f"""
    <div class="top-paper">
        <div class="rank">{rank}</div>
        <div class="top-paper-content">
            <div class="top-paper-title"><a href="{p['url']}" target="_blank">{html.escape(p['title'])}</a></div>
            <div class="top-paper-authors">{html.escape(authors)}</div>
            <div class="top-paper-tags">{tags_html}</div>
        </div>
    </div>
    """

week_top_html = "\n".join([render_top_paper(p, i+1) for i, p in enumerate(week_top)])

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
        .paper-authors {{ color: #888; font-size: 13px; margin-bottom: 5px; }}
        .paper-date {{ color: #666; font-size: 12px; margin-bottom: 10px; }}
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
        .top-paper-authors {{ color: #888; font-size: 12px; margin-bottom: 6px; }}
        .top-paper-tags {{ display: flex; gap: 4px; flex-wrap: wrap; }}
        
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
            <div class="fav-count" onclick="showFavs()">收藏 (<span id="favCount">0</span>)</div>
        </header>
        
        <div class="main-content">
            <div class="sidebar">
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
                    <input type="text" id="search" placeholder="搜索标题、作者、摘要..." oninput="filterPapers()">
                    <span class="search-hint">按 / 快速搜索</span>
                </div>
                
                <div class="top-section">
                    <h2>本周必看 10 篇</h2>
                    <div class="top-papers">
                        {week_top_html}
                    </div>
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
                
                <div id="emptyState" style="display:none;text-align:center;padding:60px 20px;color:#666">
                    <div style="font-size:48px;margin-bottom:15px">🔍</div>
                    <p style="margin-bottom:10px">没有找到匹配的论文</p>
                    <p style="font-size:13px">试试换个关键词，或者清除筛选条件</p>
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
        let showOnlyFavs = false;
        let favorites = JSON.parse(localStorage.getItem('favorites') || '[]');
        
        function updateFavCount() {{
            document.getElementById('favCount').textContent = favorites.length;
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
        
        function showFavs() {{
            showOnlyFavs = !showOnlyFavs;
            filterPapers();
        }}
        
        function filterPapers() {{
            const search = document.getElementById('search').value.toLowerCase();
            const cards = document.querySelectorAll('.paper-card');
            let visibleCount = 0;
            
            cards.forEach(card => {{
                const titleEl = card.querySelector('.paper-title');
                const authorsEl = card.querySelector('.paper-authors');
                const abstractEl = card.querySelector('.paper-abstract');
                const tags = card.dataset.tags || '';
                
                const title = titleEl.textContent.toLowerCase();
                const authors = authorsEl.textContent.toLowerCase();
                const abstract = abstractEl.textContent.toLowerCase();
                
                const matchSearch = title.includes(search) || authors.includes(search) || abstract.includes(search);
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
                
                const visible = matchSearch && matchTag && matchProperty && matchFav && matchTime;
                card.style.display = visible ? 'block' : 'none';
                if (visible) visibleCount++;
                
                // 搜索高亮
                if (search && visible) {{
                    highlightText(titleEl, search);
                    highlightText(abstractEl, search);
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
            
            // 空状态
            const emptyState = document.getElementById('emptyState');
            if (visibleCount === 0) {{
                emptyState.style.display = 'block';
            }} else {{
                emptyState.style.display = 'none';
            }}
        }}
        
        function highlightText(el, keyword) {{
            if (!el.dataset.originalHtml) {{
                el.dataset.originalHtml = el.innerHTML;
            }}
            const original = el.dataset.originalHtml;
            const escaped = keyword.replace(/[.*+?^$()|[\]\\]/g, '\\$&');
            const regex = new RegExp('(' + escaped + ')', 'gi');
            el.innerHTML = original.replace(regex, '<mark>$1</mark>');
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
        
        function filterByTag(tag) {{
            currentTag = tag;
            document.querySelectorAll('.sidebar-item').forEach(item => item.classList.remove('active'));
            event.target.classList.add('active');
            filterPapers();
        }}
        
        function filterByProperty(property, value) {{
            currentProperty = property;
            currentPropertyValue = value ? 'true' : 'false';
            filterPapers();
        }}
        
        function filterByTime(days) {{
            currentTimeRange = days;
            document.querySelectorAll('.sidebar-item').forEach(item => item.classList.remove('active'));
            event.target.classList.add('active');
            filterPapers();
        }}
        
        function clearAllFilters() {{
            currentTag = '';
            currentProperty = '';
            currentPropertyValue = '';
            currentTimeRange = 0;
            showOnlyFavs = false;
            document.getElementById('search').value = '';
            document.querySelectorAll('.sidebar-item').forEach(item => item.classList.remove('active'));
            document.querySelector('.sidebar-item').classList.add('active');
            filterPapers();
        }}
        
        function exportFavs() {{
            if (favorites.length === 0) {{
                alert('还没有收藏的论文');
                return;
            }}
            
            let md = '# 我的收藏 - 具身智能看板\n\n';
            const cards = document.querySelectorAll('.paper-card');
            let count = 0;
            
            cards.forEach(card => {{
                if (favorites.includes(card.dataset.id)) {{
                    count++;
                    const title = card.querySelector('.paper-title a').textContent;
                    const url = card.querySelector('.paper-title a').href;
                    const authors = card.querySelector('.paper-authors').textContent;
                    const tags = card.dataset.tags;
                    md += `## ${{count}}. ${{title}}\n\n`;
                    md += `- **作者**: ${{authors}}\n`;
                    md += `- **标签**: ${{tags}}\n`;
                    md += `- **链接**: ${{url}}\n\n`;
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
            const tags = card.dataset.tags.split(' ');
            const related = [];
            
            document.querySelectorAll('.paper-card').forEach(c => {{
                if (c.dataset.id !== id) {{
                    const cTags = c.dataset.tags.split(' ');
                    const overlap = tags.filter(t => cTags.includes(t)).length;
                    if (overlap >= 1) {{
                        related.push({{
                            title: c.querySelector('.paper-title').textContent,
                            url: c.querySelector('.paper-title a').href,
                            overlap: overlap
                        }});
                    }}
                }}
            }});
            
            related.sort((a, b) => b.overlap - a.overlap);
            
            const modal = document.getElementById('modal');
            const body = document.getElementById('modalBody');
            body.innerHTML = '<h2 style="margin-bottom:20px;color:#fff">相关论文</h2>' + 
                related.slice(0, 10).map(r => 
                    `<div style="margin-bottom:12px"><a href="${{r.url}}" target="_blank" style="color:#4da6ff;text-decoration:none">${{r.title}}</a></div>`
                ).join('');
            modal.style.display = 'block';
        }}
        
        function closeModal() {{
            document.getElementById('modal').style.display = 'none';
        }}
        
        // 初始化
        updateFavCount();
        updateFavButtons();
        showOnboarding();
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
