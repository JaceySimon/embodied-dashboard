"""
公司 HTML 新闻采集器
针对没有 RSS feed 的现代公司网站（Physical Intelligence / Figure / 1X / Skild），
直接抓取新闻列表页 + 文章详情页。
"""
import re
import time
import hashlib
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
    r"welcoming .{0,30} as (cfo|vp|svp|chief|officer|president|head|people|engineering)",
    r"welcoming .{0,25} (president|minister|prime minister|delegation|ambassador)",
    r"joins .{0,20} as (cfo|vp|svp|chief|ceo|officer)",
    r"time magazine", r"magazine cover", r"kung fu",
    r"investor day", r"analyst day", r"stockholders", r"\bnyse\b", r"\bnasdaq\b", r"prospectus",
    r"ask a roboticist", r"skillbridge", r"opens? .{0,20} office", r"time\s?100",
    r"reports? (first|second|third|fourth|fiscal|quarterly|annual)", r"quarterly results",
    r"融资", r"pre-?ipo", r"上市",
    # 比赛/运动会/预订营销/人物荣誉
    r"金牌", r"运动会", r"夺金", r"霸榜", r"火热预订", r"开放预订",
    r"巡回挑战赛", r"合作伙伴", r"招募", r"高燃开赛",
    r"科协", r"全国委员", r"科技报国",
    # 出货量产/签约/估值
    r"万台", r"规模化交付", r"正式下线", r"战略签约", r"估值",
    # 节日/榜单/媒体曝光/营销噱头/商业展会
    r"中秋快乐", r"新年快乐", r"春节快乐", r"节日(快乐|祝福)",
    r"福布斯", r"创新力企业", r"50强", r"百强",
    r"央视", r"新闻联播", r"点赞", r"媒体聚焦",
    r"搭子", r"七夕", r"丘比特", r"逛街", r"网红景点", r"旅游搭子",
    r"\bCES\b", r"GITEX", r"WAIC", r"迪拜", r"科幻大会", r"会展担当",
    # 出货量/市场排名
    r"shipments", r"market share", r"counterpoint", r"idc data", r"ranks? no",
    # 获奖/展会/主题乐园/巡演/行业峰会
    r"gold medal", r"innovation award", r"recognized by", r"\bifa\b", r"\bleap\b",
    r"theme park", r"resorts world", r"talent ecosystem",
    r"brings? apc \d{4}", r"hosts? .{0,10}apc", r"vivatech", r"industry summit",
    r"partner conference",
]
# 弱噪音：办公扩张/战略合作/播客/展会泛指，需同时无技术词才排除
NOISE_WEAK = [
    r"no\.?\s*1", r"ranks? ", r"trade ?show", r"expo",
    r"showcases? .{0,15}(at|expo|summit|fair)", r"expands? .{0,15} presence",
    r"partner(s)? (with|for) .{0,40}(ecosystem|innovation center|talent)",
    r"podcast",
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

# 媒体专属噪音：自家大会推广/固定栏目合集/倒计时/读者活动
MEDIA_NOISE_STRONG = [
    r"techcrunch disrupt", r"\bdisrupt 20\d{2}\b", r"\d+ (days|hours) to ",
    r"last day", r"save \d+%", r"lock in your", r"hear directly from",
    r"video friday", r"a day in the life of", r"^\s*q&a\b", r"newsletter",
    r"epics? in ieee", r"webinar", r"register now", r"buy tickets",
]
_MEDIA_NOISE_RE = re.compile("|".join(MEDIA_NOISE_STRONG), re.I)


def is_company_noise(title: str) -> bool:
    """公司/实验室博客标题是否为商业/IR/PR 噪音（True=应过滤）"""
    if _NOISE_STRONG_RE.search(title):
        return True
    if _NOISE_WEAK_RE.search(title) and not _TECH_RE.search(title):
        return True
    return False


def is_media_noise(title: str) -> bool:
    """媒体标题是否为大会广告/固定栏目合集（True=应过滤）"""
    return bool(_MEDIA_NOISE_RE.search(title))


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

    # 中文日期：2026年5月25日 / 2026年05月25日
    m = re.search(r"(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日?", raw)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass

    # 斜杠/点分隔：2026/09/23 / 2026.9.23
    m = re.search(r"(20\d{2})[/\.](\d{1,2})[/\.](\d{1,2})", raw)
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

    # 2.5 内嵌 JSON（Next.js/Sanity/CMS）的显式发布字段。
    # 注意 _createdAt/_updatedAt 是 CMS 内部迁移时间，不可用；要取业务字段 date/publishedAt。
    for field in ["datePublished", "publishedAt", "publishDate", "firstPublishedAt",
                  "published_date", r'"date"']:
        m = re.search(field + r'\s*:\s*"?(20\d{2}-\d{2}-\d{2}T[^"<\\\s]+)', html_text)
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

            # 标题：优先内部标题元素（h1-h5 / class 含 title），再退到开标签 title 属性 / img alt
            candidates = []
            ht = inner_soup.find(["h1", "h2", "h3", "h4", "h5"])
            if ht:
                candidates.append(ht.get_text(" ", strip=True))
            ct = inner_soup.find(class_=re.compile(r"title|heading|name", re.I))
            if ct:
                candidates.append(ct.get_text(" ", strip=True))
            tm = re.search(r'\btitle=["\'](.*?)["\']', attrs, re.I | re.S)
            if tm:
                candidates.append(unescape(tm.group(1)).strip())
            img = inner_soup.find("img")
            if img and img.get("alt"):
                candidates.append(unescape(img["alt"]).strip())
            # 取最长的合理候选（避开分类标签等短文本）
            candidates = [c for c in candidates if c and len(c) >= 6]
            title = max(candidates, key=len) if candidates else ""
            if not title:
                continue

            # 日期：内部 class 含 time/date/pub，或正则（支持中文/斜杠/连字符）
            # 注意只在"可见文本"里找，避免 img src 中的上传日期污染
            inner_text = inner_soup.get_text(" ", strip=True)
            date = None
            date_el = inner_soup.find(class_=re.compile(r"time|date|pub", re.I))
            if date_el:
                date = parse_date(date_el.get_text(" ", strip=True))
            if not date:
                dm = re.search(
                    r"(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日?|"
                    r"(20\d{2})[-/\.](\d{1,2})[-/\.](\d{1,2})", inner_text)
                if dm:
                    if dm.group(1):
                        date = parse_date(f"{dm.group(1)}-{dm.group(2)}-{dm.group(3)}")
                    else:
                        date = parse_date(f"{dm.group(4)}-{dm.group(5)}-{dm.group(6)}")

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
        return not is_company_noise(title)

    @staticmethod
    def _stable_id(url: str) -> str:
        """用稳定的 URL slug（或 md5 前 10 位）生成 id，避免内置 hash() 跨进程随机。"""
        slug = ""
        m = re.search(r"/([^/?#]+)/?(?:\?.*)?$", url)
        if m:
            slug = re.sub(r"\.(html?|aspx?|php)$", "", m.group(1)).lower()
            slug = re.sub(r"[^a-z0-9]+", "-", slug).strip("-")
        if len(slug) < 4:
            slug = hashlib.md5(url.encode("utf-8")).hexdigest()[:10]
        return slug[:80]

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
            id=f"html:{self.source_name.lower().replace(' ', '_')}:{self._stable_id(url)}",
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


class NuxtPayloadCollector(CompanyHTMLCollector):
    """Nuxt 站点采集器：页面是 JS 渲染，但 <route>/_payload.json 暴露完整数据。
    典型：银河通用（正文外链微信公众号，只取列表标题+链接+日期，不抓正文）。"""

    def _resolve_ref(self, arr, idx, depth=0):
        """Nuxt payload 是扁平引用数组：对象字段值是指向数组其他位置的索引"""
        if depth > 6 or not isinstance(idx, int) or idx >= len(arr):
            return idx
        v = arr[idx]
        if isinstance(v, dict):
            out = {}
            for k, vi in v.items():
                out[k] = self._resolve_ref(arr, vi, depth + 1) if isinstance(vi, int) else vi
            return out
        if isinstance(v, list):
            return [self._resolve_ref(arr, x, depth + 1) if isinstance(x, int) else x for x in v]
        return v

    def _fetch_payload(self):
        """拉列表页 HTML 拿 build id，再取 _payload.json，返回扁平数组"""
        html_text = self._get(self.list_url)
        m = re.search(r'/_nuxt/builds/meta/([a-f0-9\-]+)\.json', html_text)
        if not m:
            raise RuntimeError(f"未找到 Nuxt build id: {self.list_url}")
        build_id = m.group(1)
        base = self.list_url.rstrip("/")
        payload_url = f"{base}/_payload.json?{build_id}"
        resp = requests.get(payload_url, headers=HEADERS, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, list) else data.get("data", data)

    def _extract_items(self, arr):
        """在扁平数组里找含 'list' 的分页对象，还原新闻条目列表"""
        for node in arr:
            if isinstance(node, dict) and "list" in node and isinstance(node["list"], int):
                list_refs = arr[node["list"]]
                if isinstance(list_refs, list):
                    items = []
                    for ref in list_refs:
                        obj = self._resolve_ref(arr, ref)
                        if isinstance(obj, dict) and "url" in obj:
                            items.append(obj)
                    if items:
                        return items
        return []

    def collect(self, lookback_days: int = 90) -> List[Paper]:
        logger.info(f"[Nuxt] 抓取 {self.source_name}: {self.list_url}")
        cutoff = datetime.utcnow() - timedelta(days=lookback_days)
        arr = self._fetch_payload()
        raw_items = self._extract_items(arr)

        papers = []
        seen = set()
        for n in raw_items:
            url = (n.get("url") or "").strip()
            if not url or url in seen:
                continue
            seen.add(url)
            # 银河通用字段名错位：真正标题在 content/eng_content
            title = (n.get("content") or n.get("title") or
                     n.get("eng_content") or "").strip()
            if not title:
                continue
            if self.noise_filter and is_company_noise(title):
                continue
            if self.keywords:
                if not any(k.lower() in title.lower() for k in self.keywords):
                    continue
            published = parse_date(str(n.get("publish_time", ""))) or datetime.utcnow()
            # 未来日期兜底
            if published > datetime.utcnow() + timedelta(days=2):
                published = datetime.utcnow()
            if published < cutoff:
                continue
            papers.append(self._make_paper(title, url, "", published))
            if len(papers) >= self.max_articles:
                break

        logger.info(f"[Nuxt] {self.source_name} 采集 {len(papers)} 篇")
        return papers


class JsonApiCollector(CompanyHTMLCollector):
    """纯 SPA 站点的后端分页 JSON 接口采集器。
    典型：星动纪元 robotera（前端 Vite SPA，/prod-api/.../getNewsList 返回列表 JSON）。
    通过 json_api 配置字段映射与分页参数，避免硬编码。"""

    def __init__(self, *args, api_config: dict = None, **kwargs):
        super().__init__(*args, **kwargs)
        cfg = api_config or {}
        self.api_params = dict(cfg.get("params", {}))
        self.page_param = cfg.get("page_param")      # 页码参数名，如 pageNum
        self.size_param = cfg.get("size_param")      # 页大小参数名，如 pageSize
        self.page_size = cfg.get("page_size", 20)    # 每页条数
        if self.size_param:
            self.api_params[self.size_param] = self.page_size
        self.list_path = cfg.get("list_path", "data.list")
        self.total_path = cfg.get("total_path", "data.total")
        self.title_field = cfg.get("title_field", "title")
        self.url_field = cfg.get("url_field", "url")
        self.date_field = cfg.get("date_field", "publishTime")
        self.api_max_pages = cfg.get("max_pages", 3)

    @staticmethod
    def _dig(obj, dotted: str):
        cur = obj
        for key in dotted.split("."):
            if isinstance(cur, dict):
                cur = cur.get(key)
            else:
                return None
        return cur

    def _fetch_page(self, page: int) -> list:
        params = dict(self.api_params)
        if self.page_param:
            params[self.page_param] = page
        resp = requests.get(self.list_url, params=params,
                            headers={**HEADERS, "Accept": "application/json"},
                            timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()
        items = self._dig(data, self.list_path)
        return items or []

    def collect(self, lookback_days: int = 90) -> List[Paper]:
        logger.info(f"[JSON-API] 抓取 {self.source_name}: {self.list_url}")
        cutoff = datetime.utcnow() - timedelta(days=lookback_days)
        papers, seen = [], set()
        for page in range(1, self.api_max_pages + 1):
            try:
                items = self._fetch_page(page)
            except Exception as e:
                logger.warning(f"[JSON-API] {self.source_name} 第{page}页失败: {e}")
                break
            if not items:
                break
            stop = False
            for n in items:
                url = (n.get(self.url_field) or "").strip() if isinstance(n, dict) else ""
                title = (n.get(self.title_field) or "").strip() if isinstance(n, dict) else ""
                if not url or not title or url in seen:
                    continue
                seen.add(url)
                if self.noise_filter and is_company_noise(title):
                    continue
                if self.keywords:
                    if not any(k.lower() in title.lower() for k in self.keywords):
                        continue
                published = parse_date(str(n.get(self.date_field, ""))) or datetime.utcnow()
                if published > datetime.utcnow() + timedelta(days=2):
                    published = datetime.utcnow()
                if published < cutoff:
                    stop = True
                    continue
                papers.append(self._make_paper(title, url, "", published))
                if len(papers) >= self.max_articles:
                    stop = True
                    break
            if stop or len(items) < self.page_size:
                break
            time.sleep(self.delay)

        logger.info(f"[JSON-API] {self.source_name} 采集 {len(papers)} 篇")
        return papers



def build_html_collectors_from_config(config: dict) -> List["CompanyHTMLCollector"]:
    """从配置文件构建所有启用的 HTML 公司采集器"""
    collectors = []
    for comp in config.get("l1", {}).get("html_companies", []):
        if comp.get("enabled", False) and comp.get("list_url"):
            mode = comp.get("mode", "detail")
            if mode == "nuxt_payload":
                cls = NuxtPayloadCollector
            elif mode == "json_api":
                cls = JsonApiCollector
            else:
                cls = CompanyHTMLCollector
            kw = dict(
                source_name=comp["name"],
                list_url=comp["list_url"],
                link_pattern=comp.get("link_pattern", ""),
                keywords=comp.get("keywords"),
                region=comp.get("region", "US"),
                max_articles=comp.get("max_articles", 12),
                mode=mode,
                page_url=comp.get("page_url"),
                max_pages=comp.get("max_pages", 1),
                source_type=comp.get("source_type", "company_blog"),
            )
            if mode == "json_api":
                kw["api_config"] = comp.get("json_api", {})
            collectors.append(cls(**kw))
    return collectors
