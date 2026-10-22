"""
X / Twitter 采集器 - 通过公共 RSSHub 实例
只收白名单账号的长线程（带链接的推文）
"""
import feedparser
from datetime import datetime, timezone
from typing import List, Optional
import re

from collectors.base import BaseCollector
from models.paper import Paper, SourceLevel, SourceType
from pipeline.clean import normalize_url, title_hash


# 公共 RSSHub 实例列表（按优先级）
RSSHUB_INSTANCES = [
    "https://rsshub.app",
    "https://rsshub.rssforever.com",
    "https://rsshub.pseudoyu.com",
]


class XCollector(BaseCollector):
    """通过 RSSHub 采集 X 账号的推文"""

    source_name = "X (Twitter)"
    source_level = SourceLevel.L1
    source_type = SourceType.X_THREAD

    def __init__(self, accounts: List[str], min_tweet_length: int = 100):
        """
        accounts: 账号列表，如 ["@sergey_levine", "@Figure_robot"]
        min_tweet_length: 推文长度阈值，只收长线程
        """
        self.accounts = [a.lstrip("@") for a in accounts]
        self.min_tweet_length = min_tweet_length

    def _try_rsshub(self, instance: str, username: str) -> Optional[feedparser.FeedParserDict]:
        """尝试从某个 RSSHub 实例获取"""
        url = f"{instance}/twitter/user/{username}"
        try:
            feed = feedparser.parse(url)
            if feed.entries:
                return feed
        except Exception:
            pass
        return None

    def collect(self, lookback_days: int = 7) -> List[Paper]:
        papers = []
        cutoff = datetime.now(timezone.utc).timestamp() - lookback_days * 86400

        for username in self.accounts:
            feed = None
            for instance in RSSHUB_INSTANCES:
                feed = self._try_rsshub(instance, username)
                if feed:
                    break

            if not feed:
                print(f"  [X:@{username}] 所有实例都失败")
                continue

            count = 0
            for entry in feed.entries:
                # 时间
                pub_ts = None
                if hasattr(entry, "published_parsed") and entry.published_parsed:
                    pub_ts = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc).timestamp()

                if pub_ts and pub_ts < cutoff:
                    continue

                title = getattr(entry, "title", "").strip()
                if not title:
                    continue

                # 过滤短推文
                if len(title) < self.min_tweet_length:
                    continue

                # 只收带链接的（链到论文/博客/代码）
                summary = getattr(entry, "summary", "")
                has_link = bool(re.search(r"https?://", summary))
                if not has_link:
                    continue

                # 找链接
                links = re.findall(r'https?://[^\s<>"\']+', summary)
                # 过滤掉 twitter.com 内部链接
                external_links = [l for l in links if "twitter.com" not in l and "x.com" not in l]

                if not external_links:
                    continue

                link = normalize_url(external_links[0])

                # 找 arXiv 链接
                arxiv_url = None
                arxiv_match = re.search(r"arxiv\.org/abs/(\d+\.\d+)", summary)
                if arxiv_match:
                    arxiv_url = f"https://arxiv.org/abs/{arxiv_match.group(1)}"

                pub_dt = datetime.fromtimestamp(pub_ts, tz=timezone.utc).replace(tzinfo=None) if pub_ts else datetime.utcnow()

                p = Paper(
                    id=f"x:{username}:{hash(link) % 100000}",
                    source_id=f"x:@{username}:{link}",
                    source_level=self.source_level,
                    source_type=self.source_type,
                    source_name=f"X/@{username}",
                    source_url=f"https://x.com/{username}",
                    title=title[:300],
                    abstract=re.sub(r"<[^>]+>", " ", summary)[:1000],
                    authors=[f"@{username}"],
                    institutions=[],
                    url=link,
                    published_at=pub_dt,
                    categories=[],
                    title_hash=title_hash(title),
                    raw_metadata={
                        "x_account": username,
                        "arxiv_linked": arxiv_url,
                        "all_links": external_links[:5],
                    },
                )
                papers.append(p)
                count += 1

            print(f"  [X:@{username}] {count} 条长线程")

        return papers
