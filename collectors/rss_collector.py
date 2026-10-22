"""
RSS 采集器 - 改进版：用 requests + BeautifulSoup fallback
解决 XML 格式不标准的 RSS 源解析问题
"""
import feedparser
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone
from typing import List, Optional
import re
import time

from collectors.base import BaseCollector
from models.paper import Paper, SourceLevel, SourceType
from pipeline.clean import normalize_url, title_hash


class RSSCollector(BaseCollector):
    """通用 RSS 采集器，带容错"""

    def __init__(self, source_name: str, rss_url: str, source_level: str,
                 source_type: str, keywords: Optional[List[str]] = None,
                 region: str = "US"):
        self.source_name = source_name
        self.rss_url = rss_url
        self.source_level = source_level
        self.source_type = source_type
        self.keywords = keywords or []
        self.region = region
        self.timeout = 8

    def _fetch_feed(self) -> Optional[feedparser.FeedParserDict]:
        """获取并解析 RSS，带容错"""
        # 方法1：直接 feedparser.parse（最简单）
        try:
            feed = feedparser.parse(self.rss_url)
            if feed.entries:
                return feed
        except Exception:
            pass

        # 方法2：用 requests 获取内容，再 feedparser.parse(content)
        try:
            resp = requests.get(self.rss_url, timeout=self.timeout, headers={
                "User-Agent": "Mozilla/5.0 (compatible; EmbodiedDashboard/1.0)"
            })
            if resp.status_code == 200:
                feed = feedparser.parse(resp.content)
                if feed.entries:
                    return feed
        except Exception:
            pass

        # 方法3：用 BeautifulSoup 解析 HTML（针对返回 HTML 的"伪 RSS"）
        try:
            resp = requests.get(self.rss_url, timeout=self.timeout, headers={
                "User-Agent": "Mozilla/5.0 (compatible; EmbodiedDashboard/1.0)"
            })
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.content, "html.parser")
                items = soup.find_all("item") or soup.find_all("entry")
                if items:
                    feed = feedparser.FeedParserDict()
                    feed.entries = []
                    for item in items:
                        entry = feedparser.FeedParserDict()
                        title_tag = item.find("title")
                        entry.title = title_tag.get_text() if title_tag else ""
                        link_tag = item.find("link")
                        if link_tag:
                            entry.link = link_tag.get_text() or link_tag.get("href", "")
                        else:
                            entry.link = ""
                        desc_tag = item.find("description")
                        entry.summary = desc_tag.get_text() if desc_tag else ""
                        pub_tag = item.find("pubDate")
                        entry.published = pub_tag.get_text() if pub_tag else ""
                        feed.entries.append(entry)
                    if feed.entries:
                        return feed
        except Exception:
            pass

        return None

    def collect(self, lookback_days: int = 7) -> List[Paper]:
        """采集最近 N 天的 RSS 条目"""
        papers = []
        cutoff = datetime.now(timezone.utc).timestamp() - lookback_days * 86400

        feed = self._fetch_feed()
        if not feed:
            print(f"  [RSS:{self.source_name}] 所有解析方式都失败")
            return []

        for entry in feed.entries:
            # 时间
            pub_ts = None
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                pub_ts = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc).timestamp()
            elif hasattr(entry, "updated_parsed") and entry.updated_parsed:
                pub_ts = datetime(*entry.updated_parsed[:6], tzinfo=timezone.utc).timestamp()

            if pub_ts and pub_ts < cutoff:
                continue

            # 标题
            title = getattr(entry, "title", "").strip()
            if not title:
                continue

            # 关键词过滤
            if self.keywords:
                title_lower = title.lower()
                if not any(kw.lower() in title_lower for kw in self.keywords):
                    continue

            # 链接
            link = getattr(entry, "link", "").strip()
            if not link:
                continue
            link = normalize_url(link)

            # 摘要
            summary = getattr(entry, "summary", "") or getattr(entry, "description", "")
            summary = re.sub(r"<[^>]+>", " ", summary)
            summary = re.sub(r"\s+", " ", summary).strip()

            # 作者
            authors = []
            if hasattr(entry, "author"):
                authors = [entry.author.strip()]

            # 找 arXiv 链接
            arxiv_url = None
            arxiv_match = re.search(r"arxiv\.org/abs/(\d+\.\d+)", summary + " " + link)
            if arxiv_match:
                arxiv_url = f"https://arxiv.org/abs/{arxiv_match.group(1)}"

            # 找 GitHub 链接
            code_url = None
            github_match = re.search(r"github\.com/([\w-]+)/([\w-]+)", summary)
            if github_match:
                code_url = f"https://github.com/{github_match.group(1)}/{github_match.group(2)}"

            pub_dt = datetime.fromtimestamp(pub_ts, tz=timezone.utc).replace(tzinfo=None) if pub_ts else datetime.utcnow()

            p = Paper(
                id=f"rss:{self.source_name.lower().replace(' ','_')}:{hash(link) % 100000}",
                source_id=f"rss:{self.source_name}:{link}",
                source_level=self.source_level,
                source_type=self.source_type,
                source_name=self.source_name,
                source_url=self.rss_url,
                title=title,
                abstract=summary[:2000] if summary else None,
                authors=authors,
                institutions=[],
                url=link,
                pdf_url=None,
                code_url=code_url,
                hf_url=None,
                published_at=pub_dt,
                categories=[],
                title_hash=title_hash(title),
                raw_metadata={
                    "region": self.region,
                    "arxiv_linked": arxiv_url,
                },
            )
            papers.append(p)

        print(f"  [RSS:{self.source_name}] {len(papers)} 篇")
        return papers


def build_rss_collectors_from_config(config: dict) -> List[RSSCollector]:
    """从配置文件构建所有启用的 RSS 采集器"""
    collectors = []

    for lab in config.get("l1", {}).get("labs", []):
        if lab.get("rss") and lab.get("enabled", True):
            collectors.append(RSSCollector(
                source_name=lab["name"],
                rss_url=lab["rss"],
                source_level=SourceLevel.L1,
                source_type=SourceType.LAB_BLOG,
                keywords=lab.get("keywords"),
                region=lab.get("region", "US"),
            ))

    for comp in config.get("l1", {}).get("companies", []):
        if comp.get("rss") and comp.get("enabled", True):
            collectors.append(RSSCollector(
                source_name=comp["name"],
                rss_url=comp["rss"],
                source_level=SourceLevel.L1,
                source_type=SourceType.COMPANY_BLOG,
                keywords=None,
                region=comp.get("region", "US"),
            ))

    for comp in config.get("l1", {}).get("chinese_companies", []):
        if comp.get("rss") and comp.get("enabled", True):
            collectors.append(RSSCollector(
                source_name=comp["name"],
                rss_url=comp["rss"],
                source_level=SourceLevel.L1,
                source_type=SourceType.COMPANY_BLOG,
                keywords=comp.get("keywords"),
                region=comp.get("region", "CN"),
            ))

    for media in config.get("l2", {}).get("media", []):
        if media.get("rss") and media.get("enabled", True):
            collectors.append(RSSCollector(
                source_name=media["name"],
                rss_url=media["rss"],
                source_level=SourceLevel.L2,
                source_type=SourceType.MEDIA,
                keywords=media.get("keywords"),
                region=media.get("region", "US"),
            ))

    return collectors
