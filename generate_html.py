"""
生成静态 HTML 展示页 v3
增加：多维筛选、全文搜索、本周热点、实验室动态
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

# 计算本周热点（最近 7 天）
week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
week_papers = [p for p in papers if p["published_at"] >= week_ago]
hot_tags = Counter()
for p in week_papers:
    for t in p["tags"]:
        hot_tags[t] += 1
hot_tags_top = hot_tags.most_common(10)

# 计算实验室动态（简单统计：按作者统计）
author_count = Counter()
for p in papers:
    for a in p["authors"][:5]:
        author_count[a] += 1
top_authors = author_count.most_common(10)

# 生成论文卡片
def render_paper(p):
    tags_html = "".join([f'<span class="tag">{html.escape(t)}</span>' for t in p["tags"][:5]])
    authors = ", ".join(p["authors"][:3])
    if len(p["authors"]) > 3:
        authors += f" et al."
    
    # 摘要
    abstract = html.escape(p.get("abstract", "")[:150] + "..." if len(p.get("abstract", "")) > 150 else p.get("abstract", ""))
    
    # 标签数据（用于筛选）
    tags_data = " ".join(p["tags"])
    has_real = "true" if p.get("has_real_robot", False) else "false"
    has_open = "true" if p.get("is_open_source", False) else "false"
    
    return f"""
    <div class="paper-card" data-tags="{html.escape(tags_data)}" data-real="{has_real}" data-open="{has_open}">
        <div class="paper-title"><a href="{p['url']}" target="_blank">{html.escape(p['title'])}</a></div>
        <div class="paper-authors">{html.escape(authors)}</div>
        <div class="paper-date">{p['published_at'][:10]}</div>
        <div class="paper-tags">{tags_html}</div>
        <div class="paper-abstract">{abstract}</div>
    </div>
    """

papers_html = "\n".join([render_paper(p) for p in papers[:200]])

# 标签选项
tags_options = "".join([f'<option value="{t}">{t} ({c})</option>' for t, c in top_tags])

# 本周热点
hot_tags_html = "".join([f'<span class="hot-tag">{t} ({c})</span>' for t, c in hot_tags_top])

# 实验室动态
top_authors_html = "".join([f'<div class="author-item">{a} <span class="count">{c} 篇</span></div>' for a, c in top_authors])

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
        }}
        h1 {{ font-size: 28px; color: #fff; margin-bottom: 10px; }}
        .stats {{ color: #888; font-size: 14px; }}
        
        /* 侧边栏 */
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
        }}
        .search-bar input {{
            width: 100%;
            padding: 12px 16px;
            background: #1a1d23;
            border: 1px solid #333;
            border-radius: 8px;
            color: #e0e0e0;
            font-size: 14px;
        }}
        
        /* 筛选 */
        .filters {{
            display: flex;
            gap: 10px;
            margin-bottom: 20px;
            flex-wrap: wrap;
        }}
        .filters select {{
            padding: 8px 12px;
            background: #1a1d23;
            border: 1px solid #333;
            border-radius: 6px;
            color: #e0e0e0;
            font-size: 13px;
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
        .paper-title {{ font-size: 16px; margin-bottom: 8px; }}
        .paper-title a {{ color: #fff; text-decoration: none; }}
        .paper-title a:hover {{ color: #4da6ff; }}
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
        }}
        
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
        .author-item {{
            display: flex;
            justify-content: space-between;
            padding: 6px 0;
            font-size: 13px;
            color: #ccc;
            border-bottom: 1px solid #222;
        }}
        .author-item:last-child {{ border-bottom: none; }}
        .count {{ color: #888; }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>具身智能看板</h1>
            <div class="stats">最近 90 天 · {len(papers)} 篇论文 · 聚焦 VLA / 世界模型 / 仿真器</div>
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
                    <h3>其他筛选</h3>
                    <div class="sidebar-item" onclick="filterByProperty('real', true)">有真机实验</div>
                    <div class="sidebar-item" onclick="filterByProperty('open', true)">已开源</div>
                </div>
            </div>
            
            <div class="content">
                <div class="search-bar">
                    <input type="text" id="search" placeholder="搜索标题、作者、摘要..." oninput="filterPapers()">
                </div>
                
                <div class="filters">
                    <select id="tagFilter" onchange="filterPapers()">
                        <option value="">所有标签</option>
                        {tags_options}
                    </select>
                </div>
                
                <div class="hot-section">
                    <h2>本周热点</h2>
                    <div class="hot-tags">
                        {hot_tags_html}
                    </div>
                </div>
                
                <div class="hot-section">
                    <h2>活跃作者</h2>
                    <div class="author-list">
                        {top_authors_html}
                    </div>
                </div>
                
                <div id="papers">
                    {papers_html}
                </div>
            </div>
        </div>
    </div>

    <script>
        let currentTag = '';
        let currentProperty = '';
        let currentPropertyValue = '';
        
        function filterPapers() {{
            const search = document.getElementById('search').value.toLowerCase();
            const tag = document.getElementById('tagFilter').value;
            const cards = document.querySelectorAll('.paper-card');
            
            cards.forEach(card => {{
                const title = card.querySelector('.paper-title').textContent.toLowerCase();
                const authors = card.querySelector('.paper-authors').textContent.toLowerCase();
                const abstract = card.querySelector('.paper-abstract').textContent.toLowerCase();
                const tags = card.dataset.tags || '';
                
                const matchSearch = title.includes(search) || authors.includes(search) || abstract.includes(search);
                const matchTag = !tag || tags.includes(tag);
                const matchSidebarTag = !currentTag || tags.includes(currentTag);
                
                let matchProperty = true;
                if (currentProperty) {{
                    matchProperty = card.dataset[currentProperty] === currentPropertyValue;
                }}
                
                card.style.display = (matchSearch && matchTag && matchSidebarTag && matchProperty) ? 'block' : 'none';
            }});
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
print(f"本周论文数: {len(week_papers)}")
