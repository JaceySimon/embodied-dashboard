"""
生成静态 HTML 展示页 v2
增加：AI 摘要、更好的样式、重点标签筛选
"""
import json
import html
from pathlib import Path
from collections import Counter

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

# 重点标签（VLA / 世界模型 / 仿真器）
key_tags = ["VLA", "world_model", "sim2real", "diffusion_policy", "foundation_model"]

# 生成论文卡片
def render_paper(p):
    tags_html = "".join([f'<span class="tag">{html.escape(t)}</span>' for t in p["tags"][:5]])
    authors = ", ".join(p["authors"][:3])
    if len(p["authors"]) > 3:
        authors += f" et al."
    code_link = f'<a href="{p["code_url"]}" target="_blank" class="code-link">Code</a>' if p.get("code_url") else ""
    
    # 摘要（如果有的话）
    abstract = html.escape(p.get("abstract", "")[:200] + "..." if len(p.get("abstract", "")) > 200 else p.get("abstract", ""))
    
    return f"""
    <div class="paper-card" data-tags="{html.escape(' '.join(p['tags']))}">
        <div class="paper-title"><a href="{p['url']}" target="_blank">{html.escape(p['title'])}</a></div>
        <div class="paper-authors">{html.escape(authors)}</div>
        <div class="paper-date">{p['published_at'][:10]}</div>
        <div class="paper-tags">{tags_html}</div>
        <div class="paper-abstract">{abstract}</div>
        <div class="paper-links">{code_link} <a href="{p['url']}" target="_blank">论文原文</a></div>
    </div>
    """

papers_html = "\n".join([render_paper(p) for p in papers[:200]])  # 只展示前 200 篇

tags_options = "".join([f'<option value="{t}">{t} ({c})</option>' for t, c in top_tags])

# 重点标签按钮
key_tags_buttons = "".join([f'<button class="key-tag-btn" onclick="filterByTag(\'{t}\')">{t}</button>' for t in key_tags])

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
        .key-tags {{
            display: flex;
            gap: 10px;
            margin-bottom: 20px;
            flex-wrap: wrap;
        }}
        .key-tag-btn {{
            padding: 8px 16px;
            background: #1e293b;
            color: #93c5fd;
            border: 1px solid #334155;
            border-radius: 20px;
            cursor: pointer;
            font-size: 14px;
            transition: all 0.2s;
        }}
        .key-tag-btn:hover {{
            background: #334155;
            border-color: #475569;
        }}
        .filters {{
            display: flex;
            gap: 15px;
            margin-bottom: 30px;
            flex-wrap: wrap;
        }}
        .filters input, .filters select {{
            padding: 10px 15px;
            background: #1a1d23;
            border: 1px solid #333;
            border-radius: 8px;
            color: #e0e0e0;
            font-size: 14px;
        }}
        .filters input {{ flex: 1; min-width: 200px; }}
        .paper-card {{
            background: #14171d;
            border: 1px solid #222;
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 15px;
            transition: border-color 0.2s;
        }}
        .paper-card:hover {{ border-color: #444; }}
        .paper-title {{ font-size: 18px; margin-bottom: 8px; }}
        .paper-title a {{ color: #fff; text-decoration: none; }}
        .paper-title a:hover {{ color: #4da6ff; }}
        .paper-authors {{ color: #888; font-size: 14px; margin-bottom: 5px; }}
        .paper-date {{ color: #666; font-size: 12px; margin-bottom: 10px; }}
        .paper-tags {{ display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 10px; }}
        .tag {{
            background: #1e293b;
            color: #93c5fd;
            padding: 3px 10px;
            border-radius: 20px;
            font-size: 12px;
        }}
        .paper-abstract {{
            color: #888;
            font-size: 13px;
            margin-bottom: 10px;
            line-height: 1.5;
        }}
        .paper-links {{ font-size: 13px; }}
        .paper-links a {{ color: #4da6ff; text-decoration: none; margin-right: 15px; }}
        .paper-links a:hover {{ text-decoration: underline; }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>具身智能看板</h1>
            <div class="stats">最近 90 天 · {len(papers)} 篇论文 · 聚焦 VLA / 世界模型 / 仿真器</div>
        </header>
        
        <div class="key-tags">
            {key_tags_buttons}
        </div>
        
        <div class="filters">
            <input type="text" id="search" placeholder="搜索论文标题/作者..." oninput="filterPapers()">
            <select id="tagFilter" onchange="filterPapers()">
                <option value="">所有标签</option>
                {tags_options}
            </select>
        </div>
        
        <div id="papers">
            {papers_html}
        </div>
    </div>

    <script>
        function filterPapers() {{
            const search = document.getElementById('search').value.toLowerCase();
            const tag = document.getElementById('tagFilter').value;
            const cards = document.querySelectorAll('.paper-card');
            
            cards.forEach(card => {{
                const title = card.querySelector('.paper-title').textContent.toLowerCase();
                const authors = card.querySelector('.paper-authors').textContent.toLowerCase();
                const tags = card.dataset.tags || '';
                
                const matchSearch = title.includes(search) || authors.includes(search);
                const matchTag = !tag || tags.includes(tag);
                
                card.style.display = (matchSearch && matchTag) ? 'block' : 'none';
            }});
        }}
        
        function filterByTag(tag) {{
            document.getElementById('tagFilter').value = tag;
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
print(f"标签数: {len(top_tags)}")
