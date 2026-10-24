"""
数据质量过滤：去噪、相关性过滤
"""
from typing import List
from models.paper import Paper
from utils import logger


# 必须包含的关键词（至少一个）
REQUIRED_KEYWORDS = [
    "vla", "vision-language-action", "vision language action",
    "world model", "world-model",
    "simulator", "simulation", "sim-to-real", "sim2real",
    "embodied", "robot foundation", "robot policy",
    "diffusion policy", "flow matching",
    "robot manipulation", "robot learning",
    "robotics", "robot",
]

# 排除的关键词（包含这些词的论文相关性低）
EXCLUDE_KEYWORDS = [
    "chatbot", "dialogue", "sentiment", "recommendation",
    "speech recognition", "machine translation",
    "image classification", "object detection",
    "medical image", "clinical", "drug",
    "financial", "stock", "trading",
]

# 高相关性标签（这些标签的论文优先）
HIGH_VALUE_TAGS = {
    "VLA": 10,
    "world_model": 8,
    "sim2real": 7,
    "diffusion_policy": 6,
    "foundation_model": 6,
    "real_robot": 5,
    "open_source": 3,
}


def is_relevant(paper: Paper) -> bool:
    """
    判断论文是否相关
    """
    text = (paper.title + " " + (paper.abstract or "")).lower()

    # 检查是否包含必须关键词
    has_required = any(kw in text for kw in REQUIRED_KEYWORDS)
    if not has_required:
        return False

    # 检查是否包含排除关键词
    has_excluded = any(kw in text for kw in EXCLUDE_KEYWORDS)
    if has_excluded:
        # 但如果同时包含高相关词，还是保留
        has_high_value = any(kw in text for kw in ["robot", "manipulation", "vla"])
        if not has_high_value:
            return False

    return True


def filter_papers(papers: List[Paper]) -> List[Paper]:
    """
    过滤不相关论文
    """
    before = len(papers)
    filtered = [p for p in papers if is_relevant(p)]
    after = len(filtered)

    if before != after:
        logger.info(f"[过滤] 去噪: {before} -> {after} (移除 {before - after} 篇不相关)")

    return filtered


def calc_paper_score(paper: Paper) -> int:
    """
    计算论文质量分数
    分数越高，排序越靠前
    """
    score = 0

    # 标签权重
    for tag in paper.tags:
        score += HIGH_VALUE_TAGS.get(tag, 1)

    # 真机实验
    if paper.has_real_robot:
        score += 5

    # 开源
    if paper.is_open_source:
        score += 3

    # 作者数量（多人合作通常更重要）
    score += min(len(paper.authors), 5)

    # 有代码链接
    if paper.code_url:
        score += 4

    # 摘要长度（摘要太短通常是短篇论文）
    if paper.abstract and len(paper.abstract) > 500:
        score += 2

    return score


def sort_papers(papers: List[Paper]) -> List[Paper]:
    """
    按质量分数排序，分数相同的按时间倒序
    """
    scored = [(calc_paper_score(p), p) for p in papers]
    scored.sort(key=lambda x: (x[0], x[1].published_at if x[1].published_at else ""), reverse=True)
    return [p for _, p in scored]
