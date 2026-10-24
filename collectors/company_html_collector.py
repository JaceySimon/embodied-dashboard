"""
公司 HTML 新闻采集器
针对没有 RSS feed 的现代公司网站（Physical Intelligence / Figure / 1X / Skild），
直接抓取新闻列表页 + 文章详情页。
"""
import re
import time
import requests
from datetime import datetime, timezone, timedelta
from typing import List, Optional
from urllib.parse import urljoin
from bs4 import BeautifulSoup

from collectors.base import BaseCollector
from models.paper import Paper, SourceLevel, SourceType
from pipeline.clean import title_hash
from utils import logger

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
}


def parse_date(raw: str) -> Optional[datetime]:
    """解析单个日期字符串，失败返回 None"""
    if not raw:
        return None
    raw = raw.strip()

    m = re.search(r"(20\d{2})-(\d{1,2})-(\d{1,2})", raw)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass

    for fmt in ("%b %d, %Y", "%B %d, %Y", "%b %d %Y", "%B %d %Y",
                "%b %d '%y", "%B %d '%y",
                "%d %b, %Y", "%d %B, %Y", "%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            pass

    m = re.search(r"([A-Z][a-z]+)\s+(\d{1,2}),?\s+(20\d{2})", raw)
    if m:
        for fmt in ("%b %d %Y", "%B %d %Y"):
            try:
                return datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}", fmt)
            except ValueError:
                pass

    # "JUN 04 '26" 形式
    m = re.search(r"([A-Z]{3,9})\s+(\d{1,2})\s*['']\s*(\d{2})", raw)
    if m:
        try:
            return datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}", "%b %d %y")
        except ValueError:
            pass

    return None


def _extract_date(soup, html_text: str) -> Optional[datetime]:
    """
    分层提取文章发布日期，规避侧边栏/页脚/相关文章污染：
    1. meta article:published_time（最可靠）
    2. JSON-LD datePublished
    3. <article>/<main> 主体内
    4. h1 之后的第一个日期（发布日期通常紧跟标题）
    5. 全页候选取最新（兜底）
    """
    # 1. meta
    tag = soup.find("meta", attrs={"property": "article:published_time"})
    if tag:
        d = parse_date(tag.get("content", ""))
        if d:
            return d

    # 2. JSON-LD
    for s in soup.find_all("script", type="application/ld+json"):
        txt = s.string or s.get_text()
        m = re.search(r'"datePublished"\s*:\s*"([^"]+)"', txt)
        if m:
            d = parse_date(m.group(1))
            if d:
                return d

    # 3. <article> / <main> 内
    scope = soup.find("article") or soup.find("main")
    if scope:
        d = _first_date_in_text(scope.get_text(" ", strip=True))
        if d:
            return d

    # 4. h1 之后的第一个日期（前 1500 字符）
    h1 = soup.find("h1")
    if h1:
        following = " ".join(t.strip() for t in h1.find_all_next(string=True) if t.strip())
        d = _first_date_in_text(following[:1500])
        if d:
            return d

    # 5. 兜底：全页取最新
    return _latest_dates(html_text)


def _first_date_in_text(text: str) -> Optional[datetime]:
    """文本里第一个可解析的日期（支持 'JUN 04 '26'、'Aug 18, 2026'、ISO）"""
    if not text:
        return None
    # 月份缩写/全称 + 日 + 年
    m = re.search(
        r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|"
        r"January|February|March|April|May|June|July|August|September|October|November|December)"
        r"\s+\d{1,2},?\s*(?:'?\d{2,4}))",
        text, re.I)
    if m:
        d = parse_date(m.group(1))
        if d:
            return d
    m = re.search(r"(20\d{2})-(\d{1,2})-(\d{1,2})", text)
    if m:
        return parse_date(m.group(0))
    return None


def _latest_dates(html_text: str) -> Optional[datetime]:
    """兜底：从整页找所有日期候选，取最新（规避 footer/站点固定旧日期）"""
    candidates = []
    for m in re.finditer(r"(20\d{2})-(\d{1,2})-(\d{1,2})", html_text):
        try:
            candidates.append(datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))))
        except ValueError:
            pass
    for m in re.finditer(r"([A-Z][a-z]+)\s+(\d{1,2}),?\s+(20\d{2})", html_text):
        d = parse_date(m.group(0))
        if d:
            candidates.append(d)
    if not candidates:
        return None
    now = datetime.utcnow() + timedelta(days=1)
    valid = [d for d in candidates if d <= now]
    return max(valid) if valid else None



class CompanyHTMLCollector(BaseCollector):
    """抓取无 RSS 的公司新闻页"""

    def __init__(self, source_name: str, list_url: str, link_pattern: str,
                 base_url: Optional[str] = None, keywords: Optional[List[str]] = None,
                 region: str = "US", delay: float = 1.0, max_articles: int = 15,
                 exclude: Optional[List[str]] = None):
        self.source_name = source_name
        self.list_url = list_url
        self.link_pattern = re.compile(link_pattern)
        self.base_url = base_url or list_url
        self.keywords = keywords or []
        self.region = region
        self.delay = delay
        self.max_articles = max_articles
        self.exclude = exclude or ["/category", "/tag/", "/page/", "/categories/",
                                   "/author/", "page-", "?"]
        self.timeout = 12

    def _get(self, url: str) -> Optional[str]:
        try:
            resp = requests.get(url, timeout=self.timeout, headers=HEADERS)
            if resp.status_code == 200:
                return resp.text
            logger.warning(f"[HTML] {self.source_name} HTTP {resp.status_code}: {url}")
        except Exception as e:
            logger.warning(f"[HTML] {self.source_name} 获取失败: {type(e).__name__}")
        return None

    def _extract_article_links(self, html_text: str) -> List[str]:
        """从列表页提取文章链接（去重保序）"""
        paths = self.link_pattern.findall(html_text)
        seen = set()
        links = []
        for path in paths:
            if any(x in path for x in self.exclude):
                continue
            # 排除纯数字结尾的分页（如 /discover/1）
            if re.search(r"/\d+$", path):
                continue
            if path in seen:
                continue
            seen.add(path)
            links.append(urljoin(self.base_url, path))
        return links[:self.max_articles]

    def _parse_article(self, url: str, html_text: str) -> Optional[dict]:
        """解析文章详情页"""
        soup = BeautifulSoup(html_text, "lxml")

        # 标题
        h1 = soup.find("h1")
        title = h1.get_text(" ", strip=True) if h1 else ""
        if not title:
            title_tag = soup.find("meta", {"property": "og:title"})
            title = title_tag.get("content", "").strip() if title_tag else ""
        if not title:
            return None

        # 日期（分层提取，规避侧边栏污染）
        published = _extract_date(soup, html_text)
        if not published:
            published = datetime.utcnow()

        # 摘要
        desc = ""
        desc_tag = soup.find("meta", {"name": "description"})
        if desc_tag:
            desc = desc_tag.get("content", "").strip()
        if not desc:
            # 取第一段正文
            p = soup.find("p")
            if p:
                desc = p.get_text(" ", strip=True)

        # 正文（前若干段）
        paragraphs = [p.get_text(" ", strip=True) for p in soup.find_all("p")]
        paragraphs = [p for p in paragraphs if len(p) > 40]
        body = " ".join(paragraphs[:8])
        abstract = (desc or body)[:1500]

        # GitHub / arXiv 链接
        code_url = None
        m = re.search(r"https?://github\.com/[\w-]+/[\w-]+", html_text)
        if m:
            code_url = m.group(0)

        return {
            "title": title,
            "abstract": abstract,
            "published_at": published,
            "code_url": code_url,
        }

    def _is_relevant(self, text: str) -> bool:
        """关键词过滤；若没配关键词则全部保留（公司博客本身相关度高）"""
        if not self.keywords:
            return True
        text_lower = text.lower()
        return any(k.lower() in text_lower for k in self.keywords)

    def collect(self, lookback_days: int = 90) -> List[Paper]:
        logger.info(f"[HTML] 抓取 {self.source_name}: {self.list_url}")
        list_html = self._get(self.list_url)
        if not list_html:
            return []

        links = self._extract_article_links(list_html)
        logger.info(f"[HTML] {self.source_name} 发现 {len(links)} 篇文章")

        cutoff = datetime.now(timezone.utc).replace(tzinfo=None)
        from datetime import timedelta
        cutoff = datetime.utcnow() - timedelta(days=lookback_days)

        papers = []
        for i, url in enumerate(links):
            if i > 0:
                time.sleep(self.delay)  # 限流，尊重对方服务器
            article_html = self._get(url)
            if not article_html:
                continue

            article = self._parse_article(url, article_html)
            if not article:
                continue

            if article["published_at"] < cutoff:
                continue

            if not self._is_relevant(article["title"] + " " + (article["abstract"] or "")):
                continue

            p = Paper(
                id=f"html:{self.source_name.lower().replace(' ', '_')}:{hash(url) % 100000}",
                source_id=f"html:{self.source_name}:{url}",
                source_level=SourceLevel.L1,
                source_type=SourceType.COMPANY_BLOG,
                source_name=self.source_name,
                source_url=self.list_url,
                title=article["title"],
                abstract=article["abstract"],
                authors=[],
                institutions=[],
                url=url,
                pdf_url=None,
                code_url=article["code_url"],
                hf_url=None,
                published_at=article["published_at"],
                categories=[],
                tags=[],
                title_hash=title_hash(article["title"]),
                raw_metadata={"collector": "company_html"},
            )
            papers.append(p)

        logger.info(f"[HTML] {self.source_name} 采集 {len(papers)} 篇")
        return papers


def build_html_collectors_from_config(config: dict) -> List["CompanyHTMLCollector"]:
    """从配置文件构建所有启用的 HTML 公司采集器"""
    collectors = []
    for comp in config.get("l1", {}).get("html_companies", []):
        if comp.get("enabled", False) and comp.get("list_url"):
            collectors.append(CompanyHTMLCollector(
                source_name=comp["name"],
                list_url=comp["list_url"],
                link_pattern=comp["link_pattern"],
                keywords=comp.get("keywords"),
                region=comp.get("region", "US"),
                max_articles=comp.get("max_articles", 12),
            ))
    return collectors
