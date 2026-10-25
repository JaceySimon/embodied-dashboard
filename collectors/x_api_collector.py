"""
X / Twitter API v2 采集器
需要 Bearer Token（X Developer Portal）。
注意：X 现按 credits 计费，免费层读取额度非常有限；
额度耗尽时 API 返回 402，采集器会自动跳过、不阻断主流程。
"""
import requests
from datetime import datetime, timezone, timedelta
from typing import List, Optional
import re
import os

from collectors.base import BaseCollector
from models.paper import Paper, SourceLevel, SourceType
from pipeline.clean import normalize_url, title_hash
from utils import detect_proxy


class XAPICollector(BaseCollector):
    """通过 X API v2 采集白名单账号的推文（含外部链接的长线程）"""

    source_name = "X (Twitter)"
    source_level = SourceLevel.L1
    source_type = SourceType.X_THREAD

    def __init__(self, accounts: List[str], bearer_token: str, min_tweet_length: int = 100):
        """
        accounts: 账号列表（不带@）
        bearer_token: X API Bearer Token
        min_tweet_length: 推文长度阈值（短推不收录）
        """
        self.accounts = [a.lstrip("@") for a in accounts]
        self.bearer_token = bearer_token
        self.min_tweet_length = min_tweet_length
        self.api_base = "https://api.twitter.com/2"
        self.proxies = detect_proxy()
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": "Bearer " + bearer_token,
            "Accept": "application/json",
            "User-Agent": "EmbodiedDashboard/1.0",
        })
        self._blocked: Optional[int] = None  # 账户级阻断（401/402/403/429），只提示一次

    def _get(self, path: str, params: Optional[dict] = None):
        """统一 GET：返回 (status, json_or_None)；账户级阻断只记录一次。"""
        if self._blocked:
            return self._blocked, None
        try:
            resp = self.session.get(self.api_base + path, params=params,
                                    proxies=self.proxies, timeout=20)
        except Exception as e:
            print("  [X] 请求失败: %s" % str(e)[:100])
            return None, None
        if resp.status_code == 200:
            return 200, resp.json()
        if resp.status_code in (401, 402, 403, 429):
            self._blocked = resp.status_code
            why = {
                401: "Token 无效（401）",
                402: "API 额度耗尽（402 credits depleted）",
                403: "Token 无该端点权限（403）",
                429: "触发速率限制（429）",
            }.get(resp.status_code)
            print("  [X] %s，本次跳过 X 采集；可检查套餐/额度或稍后重试。" % why)
            return resp.status_code, None
        print("  [X] 非预期状态码 %d: %s" % (resp.status_code, resp.text[:100]))
        return resp.status_code, None

    def _get_user_id(self, username: str) -> Optional[str]:
        """获取用户 ID"""
        status, data = self._get("/users/by/username/%s" % username)
        if status == 200 and data:
            return (data.get("data") or {}).get("id")
        return None

    def _get_user_tweets(self, user_id: str, username: str, max_results: int = 50) -> List[Paper]:
        """获取用户近期推文，筛出含外部链接的长线程"""
        params = {
            "max_results": max_results,
            "tweet.fields": "created_at,public_metrics,entities",
            "expansions": "attachments.media_keys",
        }
        status, payload = self._get("/users/%s/tweets" % user_id, params)
        if status != 200 or not payload:
            return []

        papers = []
        for tweet in payload.get("data", []):
            text = tweet.get("text", "")
            if len(text) < self.min_tweet_length:
                continue

            urls = (tweet.get("entities") or {}).get("urls", [])
            if not urls:
                continue

            # 过滤 X 内部链接，保留外部链接
            external_urls = []
            for u in urls:
                expanded = u.get("expanded_url", u.get("url", ""))
                if expanded and "twitter.com" not in expanded and "x.com" not in expanded:
                    external_urls.append(expanded)
            if not external_urls:
                continue

            # 找 arXiv 链接（若有）
            arxiv_url = None
            for u in external_urls:
                m = re.search(r"arxiv\.org/(?:abs|pdf)/(\d+\.\d+)", u)
                if m:
                    arxiv_url = "https://arxiv.org/abs/%s" % m.group(1)
                    break

            created_at = tweet.get("created_at")
            if created_at:
                pub_dt = datetime.fromisoformat(created_at.replace("Z", "+00:00")).replace(tzinfo=None)
            else:
                pub_dt = datetime.utcnow()

            link = normalize_url(external_urls[0])
            papers.append(Paper(
                id="x:%s:%s" % (username, tweet["id"]),
                source_id="x:@%s:%s" % (username, tweet["id"]),
                source_level=self.source_level,
                source_type=self.source_type,
                source_name="X/@%s" % username,
                source_url="https://x.com/%s/status/%s" % (username, tweet["id"]),
                title=text[:300],
                abstract=text[:1000],
                authors=["@%s" % username],
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
            ))
        return papers

    def collect(self, lookback_days: int = 7) -> List[Paper]:
        """采集所有白名单账号近 lookback_days 天的推文"""
        all_papers = []
        cutoff = datetime.utcnow() - timedelta(days=lookback_days)

        for username in self.accounts:
            if self._blocked:
                break
            user_id = self._get_user_id(username)
            if not user_id:
                if not self._blocked:
                    print("  [X:@%s] 未取到 user_id，跳过" % username)
                continue

            papers = self._get_user_tweets(user_id, username)
            papers = [p for p in papers if p.published_at >= cutoff]
            all_papers.extend(papers)
            print("  [X:@%s] %d 条含外链的长线程" % (username, len(papers)))

        return all_papers


def build_x_collector_from_config(config: dict) -> Optional[XAPICollector]:
    """从配置构建 X 采集器；需要在 sources.yaml 启用且环境变量提供 Token。"""
    x_cfg = config.get("l1", {}).get("x_whitelist", {})
    if not x_cfg.get("enabled", False):
        return None

    bearer_token = os.environ.get("X_BEARER_TOKEN")
    if not bearer_token:
        print("  [X] 未设置 X_BEARER_TOKEN，跳过")
        return None

    return XAPICollector(
        accounts=x_cfg.get("accounts", []),
        bearer_token=bearer_token,
    )
