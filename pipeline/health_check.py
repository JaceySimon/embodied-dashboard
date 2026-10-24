"""
数据源健康检查
检查每个 RSS 源是否可访问、能返回多少条数据
"""
import sys
import yaml
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import feedparser
import requests
from utils import logger


def check_rss(name: str, rss_url: str, timeout: int = 10) -> dict:
    """检查单个 RSS 源"""
    result = {"name": name, "url": rss_url, "status": "unknown", "count": 0, "error": ""}
    try:
        resp = requests.get(rss_url, timeout=timeout, headers={
            "User-Agent": "Mozilla/5.0 (compatible; EmbodiedDashboard/1.0)"
        })
        if resp.status_code != 200:
            result["status"] = "fail"
            result["error"] = f"HTTP {resp.status_code}"
            return result

        feed = feedparser.parse(resp.content)
        if feed.bozo and not feed.entries:
            result["status"] = "fail"
            result["error"] = str(feed.bozo_exception)[:100]
            return result

        result["status"] = "ok"
        result["count"] = len(feed.entries)

        # 最新一条日期
        if feed.entries:
            latest = feed.entries[0].get("published_parsed") or feed.entries[0].get("updated_parsed")
            if latest:
                result["latest"] = datetime(*latest[:6]).strftime("%Y-%m-%d")

    except requests.exceptions.Timeout:
        result["status"] = "timeout"
        result["error"] = "超时"
    except Exception as e:
        result["status"] = "fail"
        result["error"] = str(e)[:100]

    return result


def main():
    with open(PROJECT_ROOT / "config" / "sources.yaml", "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    sources = []

    # 收集所有 RSS 源
    for lab in config["l1"]["labs"]:
        if lab.get("rss"):
            sources.append((lab["name"], lab["rss"], lab.get("enabled", False)))

    for media in config["l2"]["media"]:
        if media.get("rss"):
            sources.append((media["name"], media["rss"], media.get("enabled", False)))

    print(f"检查 {len(sources)} 个 RSS 源...")
    print("=" * 70)

    ok_count = 0
    fail_count = 0
    disabled_count = 0

    for name, url, enabled in sources:
        if not enabled:
            print(f"⏸  [禁用] {name}")
            disabled_count += 1
            continue

        result = check_rss(name, url)
        if result["status"] == "ok":
            latest = result.get("latest", "unknown")
            print(f"✓ [正常] {name}: {result['count']} 条, 最新 {latest}")
            ok_count += 1
        else:
            print(f"✗ [失败] {name}: {result['error']}")
            fail_count += 1

    print("=" * 70)
    print(f"正常: {ok_count}, 失败: {fail_count}, 禁用: {disabled_count}")

    if fail_count > 0:
        print("\n失败的源需要在 config/sources.yaml 中更新 RSS URL 或禁用")


if __name__ == "__main__":
    main()
