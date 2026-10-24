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

# 强噪音：纯金融/人事/投资者关系/品牌栏目/办公室/展会/获奖/出货量/主题乐园，标题命中即排除
NOISE_STRONG = [
    r"registration statement", r"\bs-?4\b", r"business combination", r"churchill capital",
    r"audit committee", r"board of directors", r"new directors", r"appoints? .*(ceo|cfo|director|chair|board)",
    r"investor day", r"analyst day", r"stockholders", r"\bnyse\b", r"\bnasdaq\b", r"prospectus",
    r"ask a roboticist", r"skillbridge", r"opens? .{0,20} office", r"time\s?100",
    r"reports? (first|second|third|fourth|fiscal|quarterly|annual)", r"quarterly results",
    # 出货量/市场排名
    r"shipments", r"market share", r"counterpoint", r"idc data", r"ranks? no",
    # 获奖/展会/主题乐园/巡演
    r"gold medal", r"innovation award", r"recognized by", r"\bifa\b", r"\bleap\b",
    r"theme park", r"resorts world", r"talent ecosystem",
]
# 弱噪音：办公扩张/战略合作/展会泛指，需同时无技术词才排除
NOISE_WEAK = [
    r"no\.?\s*1", r"ranks? ", r"trade ?show", r"expo",
    r"showcases? .{0,15}(at|expo|summit|fair)", r"expands? .{0,15} presence",
    r"partner(s)? (with|for) .{0,40}(ecosystem|innovation center|talent)",
]
# 技术词：命中任一即认为有技术含量，弱噪音豁免（仅看标题）
TECH_HINTS = [
    r"robot", r"humanoid", r"\bai\b", r"model", r"learning", r"vision", r"policy", r"dataset",
    r"foundation", r"nvidia", r"gpu", r"compute", r"manipulation", r"locomotion", r"\bsim",
    r"dexter", r"\bhand\b", r"neural", r"transformer", r"diffusion", r"\bvla\b", r"reinforcement",
    r"imitation", r"perception", r"reasoning", r"benchmark", r"algorithm", r"battery",
    r"sensor", r"\bgrasp", r"dexterous", r"open[- ]?source", r"introducing",
    r"unveils? .*(robot|digit|model|system)", r"deploy",
    r"开源", r"发布", r"模型", r"数据", r"算法", r"具身", r"机器",
]
_NOISE_STRONG_RE = re.compile("|".join(NOISE_STRONG), re.I)
_NOISE_WEAK_RE = re.compile("|".join(NOISE_WEAK), re.I)
_TECH_RE = re.compile("|".join(TECH_HINTS), re.I)


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
                 exclude: Optional[List[str]] = None,
                 mode: str = "detail", page_url: Optional[str] = None,
                 max_pages: int = 1, source_type: str = "company_blog",
                 noise_filter: bool = True):
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
        # mode: "detail"=抓列表+逐篇详情；"list"=只从列表卡片提取（适合详情页JS渲染的站点）
        self.mode = mode
        self.page_url = page_url  # 分页模板，如 "https://x.com/news?page={page}"
        self.max_pages = max_pages
        self.source_type = source_type
        self.noise_filter = noise_filter

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

    def _parse_list_cards(self, html_text: str) -> List[dict]:
        """
        从列表页直接提取文章卡片（标题+链接+日期），不抓详情页。
        适配详情页 JS 渲染、但列表页是静态 HTML 的站点（如智元）。
        用正则定位 <a>，规避 lxml 对 <a><div> 嵌套的容错丢 href 问题。
        """
        from html import unescape
        cards = []
        seen = set()
        # 匹配 <a ...href="URL"...> 开标签
        for m in re.finditer(r'<a\b([^>]*?)\bhref=["\']([^"\']+)["\']([^>]*)>',
                             html_text, re.I):
            attrs = (m.group(1) or "") + " " + (m.group(3) or "")
            href = m.group(2)
            if not self.link_pattern.search(href):
                continue
            if any(x in href for x in self.exclude):
                continue

            # 取 a 标签内部片段（到对应 </a>）
            start = m.end()
            end = html_text.find("</a>", start)
            inner = html_text[start: end if end != -1 else start + 3000][:3000]
            inner_soup = BeautifulSoup(inner, "lxml")

            # 标题：开标签 title 属性与内部 h1-h5 取较长者（title 属性可能含未转义引号被截断）
            tm = re.search(r'\btitle=["\'](.*?)["\']', attrs, re.I | re.S)
            title_attr = unescape(tm.group(1)).strip() if tm else ""
            title_h5 = ""
            ht = inner_soup.find(["h1", "h2", "h3", "h4", "h5"])
            if ht:
                title_h5 = ht.get_text(" ", strip=True)
            title = title_h5 if len(title_h5) > len(title_attr) else title_attr
            if not title:
                continue

            # 日期：内部 class 含 time/date/pub，或正则
            date = None
            date_el = inner_soup.find(class_=re.compile(r"time|date|pub", re.I))
            if date_el:
                date = parse_date(date_el.get_text(" ", strip=True))
            if not date:
                dm = re.search(r"(20\d{2})[-./](\d{1,2})[-./](\d{1,2})", inner)
                if dm:
                    date = parse_date(dm.group(0).replace(".", "-").replace("/", "-"))

            full_url = urljoin(self.base_url, href)
            if full_url in seen:
                continue
            seen.add(full_url)
            cards.append({
                "title": title,
                "url": full_url,
                "published_at": date,
                "abstract": "",
            })
        return cards

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

    def _is_relevant(self, title: str, abstract: str = "") -> bool:
        """相关性 + 噪音过滤。
        正向关键词匹配标题+摘要；商业/IR 噪音只看标题（PR 性质由标题决定，
        避免正文出现 robot 词就豁免）。"""
        if self.keywords:
            full = (title + " " + abstract).lower()
            if not any(k.lower() in full for k in self.keywords):
                return False
        if not self.noise_filter:
            return True
        # 强噪音：标题命中即排除
        if _NOISE_STRONG_RE.search(title):
            return False
        # 弱噪音：标题命中且无任何技术词才排除
        if _NOISE_WEAK_RE.search(title) and not _TECH_RE.search(title):
            return False
        return True

    def _make_paper(self, title: str, url: str, abstract: str,
                    published: datetime, code_url=None) -> Paper:
        # 未来超过 2 天的日期几乎肯定是解析错误（页脚/版本号污染），回退为今天
        if published and published > datetime.utcnow() + timedelta(days=2):
            published = datetime.utcnow()
        # 来源类型映射
        st = SourceType.COMPANY_BLOG
        if self.source_type == "lab_blog":
            st = SourceType.LAB_BLOG
        elif self.source_type == "media":
            st = SourceType.MEDIA
        return Paper(
            id=f"html:{self.source_name.lower().replace(' ', '_')}:{hash(url) % 100000}",
            source_id=f"html:{self.source_name}:{url}",
            source_level=SourceLevel.L1,
            source_type=st,
            source_name=self.source_name,
            source_url=self.list_url,
            title=title,
            abstract=abstract or "",
            authors=[],
            institutions=[],
            url=url,
            pdf_url=None,
            code_url=code_url,
            hf_url=None,
            published_at=published,
            categories=[],
            tags=[],
            title_hash=title_hash(title),
            raw_metadata={"collector": "company_html", "mode": self.mode},
        )

    def collect(self, lookback_days: int = 90) -> List[Paper]:
        logger.info(f"[HTML] 抓取 {self.source_name}: {self.list_url}")
        cutoff = datetime.utcnow() - timedelta(days=lookback_days)

        # 列表页 URL（可能多页）
        list_urls = [self.list_url]
        if self.mode == "list" and self.page_url and self.max_pages > 1:
            for pg in range(2, self.max_pages + 1):
                list_urls.append(self.page_url.format(page=pg))

        papers = []
        seen_urls = set()
        if self.mode == "list":
            # 只从列表卡片提取
            for li, lu in enumerate(list_urls):
                if li > 0:
                    time.sleep(self.delay)
                html_text = self._get(lu)
                if not html_text:
                    continue
                cards = self._parse_list_cards(html_text)
                logger.info(f"[HTML] {self.source_name} 列表卡片 {len(cards)} 篇 ({lu})")
                for c in cards:
                    if len(papers) >= self.max_articles:
                        break
                    if c["url"] in seen_urls:  # 跨页去重（轮播图重复）
                        continue
                    pub = c["published_at"] or datetime.utcnow()
                    if pub < cutoff:
                        continue
                    if not self._is_relevant(c["title"], c["abstract"]):
                        continue
                    seen_urls.add(c["url"])
                    papers.append(self._make_paper(c["title"], c["url"], c["abstract"], pub))
            logger.info(f"[HTML] {self.source_name} 采集 {len(papers)} 篇")
            return papers

        # detail 模式：抓列表 + 逐篇详情
        list_html = self._get(self.list_url)
        if not list_html:
            return []

        links = self._extract_article_links(list_html)
        logger.info(f"[HTML] {self.source_name} 发现 {len(links)} 篇文章")

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

            if not self._is_relevant(article["title"], article["abstract"] or ""):
                continue

            papers.append(self._make_paper(
                article["title"], url, article["abstract"],
                article["published_at"], article["code_url"]))

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
                mode=comp.get("mode", "detail"),
                page_url=comp.get("page_url"),
                max_pages=comp.get("max_pages", 1),
                source_type=comp.get("source_type", "company_blog"),
            ))
    return collectors
