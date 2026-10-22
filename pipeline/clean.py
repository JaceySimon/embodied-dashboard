"""
数据清洗与去重工具
"""
import re
from urllib.parse import urlparse, urlunparse
from typing import Optional
import hashlib


def normalize_url(url: str) -> str:
    """规范化 URL：去 UTM、统一 https、去 www、去尾部斜杠"""
    if not url:
        return ""

    parsed = urlparse(url)

    # 统一 scheme
    scheme = "https"

    # 去 www
    netloc = parsed.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]

    # 去 UTM 等跟踪参数
    path = parsed.path
    if path.endswith("/"):
        path = path[:-1]

    # 只保留主要查询参数（v1 全去，v2 按需）
    query = ""

    # 去 fragment
    fragment = ""

    return urlunparse((scheme, netloc, path, "", query, fragment))


def normalize_title(title: str) -> str:
    """规范化标题用于去重：小写、去标点、去多余空格"""
    t = title.lower()
    # 去标点
    t = re.sub(r"[^\w\s]", " ", t)
    # 去多余空格
    t = re.sub(r"\s+", " ", t).strip()
    return t


def title_hash(title: str) -> str:
    """计算标题哈希（精确去重用）"""
    norm = normalize_title(title)
    return hashlib.md5(norm.encode()).hexdigest()


def title_similarity(title1: str, title2: str) -> float:
    """计算两个标题的相似度（Jaccard，基于词集合）"""
    words1 = set(normalize_title(title1).split())
    words2 = set(normalize_title(title2).split())

    if not words1 or not words2:
        return 0.0

    intersection = words1 & words2
    union = words1 | words2
    return len(intersection) / len(union)


def deduplicate_papers(papers, threshold: float = 0.6):
    """
    对 Paper 列表去重：
    1. 精确匹配（URL 规范化后相同）
    2. 标题相似度 > threshold 视为同一篇

    返回：unique_papers, duplicate_groups
    """
    seen_urls = {}  # normalized_url -> paper index
    seen_title_hashes = {}  # title_hash -> paper index
    duplicates = []  # (original, duplicate, method)

    unique = []

    for i, paper in enumerate(papers):
        # 第一层：URL 规范化
        norm_url = normalize_url(paper.url)
        if norm_url in seen_urls:
            orig_idx = seen_urls[norm_url]
            duplicates.append((orig_idx, i, "url"))
            continue

        # 第二层：标题精确匹配
        t_hash = title_hash(paper.title)
        if t_hash in seen_title_hashes:
            orig_idx = seen_title_hashes[t_hash]
            duplicates.append((orig_idx, i, "title_exact"))
            continue

        # 第三层：标题相似度
        is_dup = False
        for j, existing in enumerate(unique):
            sim = title_similarity(paper.title, existing.title)
            if sim >= threshold:
                duplicates.append((j, len(unique), "title_similarity"))
                is_dup = True
                break

        if is_dup:
            continue

        # 新论文
        seen_urls[norm_url] = len(unique)
        seen_title_hashes[t_hash] = len(unique)
        unique.append(paper)

    return unique, duplicates
