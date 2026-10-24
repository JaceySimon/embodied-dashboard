"""
链接可靠性检查
并发检查"本周必看 + 工业界/媒体"等高优先级链接的可达性，
找出死链（HTTP 4xx/5xx、超时、SSL 错误）。

用法:
    python pipeline/link_check.py           # 检查本周 + 工业界
    python pipeline/link_check.py all       # 检查全部（慢）
"""
import re
import json
import sys
import time
from pathlib import Path
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
from utils import find_latest_file, logger

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
}

# 格式即可信的稳定链接（这些平台 abs/页面几乎不会失效，且会对高频 HEAD 限流）
TRUSTED_PATTERNS = [
    r"^https?://arxiv\.org/(abs|pdf)/\d{4}\.\d{4,5}",
    r"^https?://(www\.)?doi\.org/",
    r"^https?://github\.com/[\w.-]+/[\w.-]+",
    r"^https?://huggingface\.co/",
]


def is_trusted(url: str) -> bool:
    return any(re.match(p, url) for p in TRUSTED_PATTERNS)


def check_link(item: dict, timeout: int = 12) -> dict:
    """检查单个链接，返回结果 dict"""
    url = item["url"]
    result = {"url": url, "title": item.get("title", "")[:60],
              "source": item.get("source_name", ""), "status": "ok", "code": None, "error": ""}

    # 可信稳定链接：格式校验即可，不发请求（避免被限流误判）
    if is_trusted(url):
        result["status"] = "trusted"
        return result

    try:
        # 用 GET + stream（部分站点不支持 HEAD），只取响应头
        r = requests.get(url, timeout=timeout, headers=HEADERS,
                         allow_redirects=True, stream=True)
        r.close()
        code = r.status_code
        result["code"] = code
        if code >= 400:
            result["status"] = "dead"
            result["error"] = f"HTTP {code}"
    except requests.exceptions.Timeout:
        # 超时再重试一次（慢速）
        time.sleep(1)
        try:
            r = requests.get(url, timeout=20, headers=HEADERS,
                             allow_redirects=True, stream=True)
            r.close()
            result["code"] = r.status_code
            if r.status_code >= 400:
                result["status"] = "dead"
                result["error"] = f"HTTP {r.status_code}"
        except Exception:
            result["status"] = "timeout"
            result["error"] = "超时"
    except requests.exceptions.SSLError:
        result["status"] = "ssl_error"
        result["error"] = "SSL 错误"
    except requests.exceptions.ConnectionError:
        result["status"] = "unreachable"
        result["error"] = "无法连接"
    except Exception as e:
        result["status"] = "error"
        result["error"] = type(e).__name__
    return result


def main():
    scope = sys.argv[1] if len(sys.argv) > 1 else "priority"

    combined_path = PROJECT_ROOT / "data" / "combined.json"
    latest = find_latest_file(PROJECT_ROOT / "data" / "backfill", "arxiv_backfill_*.json")
    path = combined_path if combined_path.exists() else latest
    papers = json.load(open(path, encoding="utf-8"))

    if scope == "all":
        targets = papers
    else:
        week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        # 本周所有 + 所有工业界/媒体
        targets = [p for p in papers
                   if p.get("published_at", "")[:10] >= week_ago
                   or p.get("source_type") in ("company_blog", "lab_blog", "media", "x_thread")]

    # 去重 URL
    seen = set()
    unique = []
    for p in targets:
        u = p.get("url")
        if u and u not in seen:
            seen.add(u)
            unique.append(p)

    print(f"检查 {len(unique)} 个链接（并发 6）...")
    print("=" * 70)

    results = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(check_link, p): p for p in unique}
        done = 0
        for fut in as_completed(futures):
            results.append(fut.result())
            done += 1
            if done % 25 == 0:
                print(f"  进度 {done}/{len(unique)}")

    # 汇总
    dead = [r for r in results if r["status"] in ("dead", "unreachable", "ssl_error", "error")]
    timeout = [r for r in results if r["status"] == "timeout"]
    trusted = [r for r in results if r["status"] == "trusted"]
    ok = [r for r in results if r["status"] == "ok"]

    print("=" * 70)
    print(f"HTTP 验证正常: {len(ok)}, 可信格式: {len(trusted)}, 死链: {len(dead)}, 超时: {len(timeout)}")

    if dead:
        print("\n【死链】")
        for r in dead:
            print(f"  ✗ [{r['source']}] {r['error']} {r['title']}")
            print(f"      {r['url']}")
    if timeout:
        print("\n【超时（可能是反爬，不一定是死链）】")
        for r in timeout[:10]:
            print(f"  ⏱ [{r['source']}] {r['title']}")

    # 保存结果
    report_path = PROJECT_ROOT / "data" / "link_check.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    json.dump(results, open(report_path, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print(f"\n报告已保存: {report_path}")

    return len(dead)


if __name__ == "__main__":
    n = main()
    sys.exit(0 if n == 0 else 2)
