"""
X / Twitter API v2 采集器
需要 Bearer Token（免费额度每月 1500 条读）
等用户提供 API key 后启用
"""
import requests
from datetime import datetime, timezone
from typing import List, Optional
import re
import os

from collectors.base import BaseCollector
from models.paper import Paper, SourceLevel, SourceType
from pipeline.clean import normalize_url, title_hash


class XAPICollector(BaseCollector):
    """通过 X API v2 采集白名单账号的推文"""

    source_name = "X (Twitter)"
    source_level = SourceLevel.L1
    source_type = SourceType.X_THREAD

    def __init__(self, accounts: List[str], bearer_token: str, min_tweet_length: int = 100):
        """
        accounts: 账号列表（不带@）
        bearer_token: X API Bearer Token
        min_tweet_length: 推文长度阈值
        """
        self.accounts = [a.lstrip("@") for a in accounts]
        self.bearer_token = bearer_token
        self.min_tweet_length = min_tweet_length
        self.api_base = "https://api.twitter.com/2"

    def _get_headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.bearer_token}",
            "Content-Type": "application/json",
        }

    def _get_user_id(self, username: str) -> Optional[str]:
        """获取用户 ID"""
        url = f"{self.api_base}/users/by/username/{username}"
        try:
            resp = requests.get(url, headers=self._get_headers(), timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                return data.get("data", {}).get("id")
        except Exception as e:
            print(f"  [X:@{username}] 获取 user_id 失败: {e}")
        return None

    def _get_user_tweets(self, user_id: str, username: str, max_results: int = 50) -> List[Paper]:
        """获取用户推文"""
        url = f"{self.api_base}/users/{user_id}/tweets"
        params = {
            "max_results": max_results,
            "tweet.fields": "created_at,public_metrics,entities",
            "expansions": "attachments.media_keys",
        }

        papers = []
        try:
            resp = requests.get(url, headers=self._get_headers(), params=params, timeout=10)
            if resp.status_code != 200:
                print(f"  [X:@{username}] API 返回 {resp.status_code}")
                return []

            data = resp.json().get("data", [])
            for tweet in data:
                text = tweet.get("text", "")
                if len(text) < self.min_tweet_length:
                    continue

                # 找链接
                entities = tweet.get("entities", {})
                urls = entities.get("urls", [])
                if not urls:
                    continue

                # 过滤 X 内部链接
                external_urls = []
                for u in urls:
                    expanded = u.get("expanded_url", u.get("url", ""))
                    if "twitter.com" not in expanded and "x.com" not in expanded:
                        external_urls.append(expanded)

                if not external_urls:
                    continue

                # 找 arXiv 链接
                arxiv_url = None
                for u in external_urls:
                    m = re.search(r"arxiv\.org/abs/(\d+\.\d+)", u)
                    if m:
                        arxiv_url = f"https://arxiv.org/abs/{m.group(1)}"
                        break

                # 时间
                created_at = tweet.get("created_at")
                if created_at:
                    pub_dt = datetime.fromisoformat(created_at.replace("Z", "+00:00")).replace(tzinfo=None)
                else:
                    pub_dt = datetime.utcnow()

                link = normalize_url(external_urls[0])

                p = Paper(
                    id=f"x:{username}:{tweet['id']}",
                    source_id=f"x:@{username}:{tweet['id']}",
                    source_level=self.source_level,
                    source_type=self.source_type,
                    source_name=f"X/@{username}",
                    source_url=f"https://x.com/{username}/status/{tweet['id']}",
                    title=text[:300],
                    abstract=text[:1000],
                    authors=[f"@{username}"],
                    institutions=[],
                    url=link,
                    published_at=pub_dt,
                    categories=[],
                    title_hash=title_hash(text[:100]),
                    raw_metadata={
                        "x_account": username,
                        "arxiv_linked": arxiv_url,
                        "all_links": external_urls[:5],
                        "tweet_id": tweet["id"],
                    },
                )
                papers.append(p)

        except Exception as e:
            print(f"  [X:@{username}] 获取推文失败: {e}")

        return papers

    def collect(self, lookback_days: int = 7) -> List[Paper]:
        """采集所有白名单账号的推文"""
        all_papers = []
        cutoff = datetime.now(timezone.utc).timestamp() - lookback_days * 86400

        for username in self.accounts:
            user_id = self._get_user_id(username)
            if not user_id:
                continue

            papers = self._get_user_tweets(user_id, username)
            # 过滤时间
            papers = [p for p in papers if p.published_at.timestamp() >= cutoff]
            all_papers.extend(papers)
            print(f"  [X:@{username}] {len(papers)} 条长线程")

        return all_papers


def build_x_collector_from_config(config: dict) -> Optional[XAPICollector]:
    """从配置构建 X 采集器，需要 API key"""
    x_cfg = config.get("l1", {}).get("x_whitelist", {})
    if not x_cfg.get("enabled", False):
        return None

    # 从环境变量读 Bearer Token
    bearer_token = os.environ.get("X_BEARER_TOKEN")
    if not bearer_token:
        print("  [X] 未设置 X_BEARER_TOKEN 环境变量，跳过")
        return None

    return XAPICollector(
        accounts=x_cfg["accounts"],
        bearer_token=bearer_token,
    )
