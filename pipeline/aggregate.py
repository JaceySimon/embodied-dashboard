"""
事件聚合器 - 把多源数据聚合成事件
规则：
1. arXiv 版本号合并（v1/v2/v3 是同一篇论文）
2. 精确匹配：URL 规范化后相同
3. arXiv 链接关联：L1/L2 内容里链到了 arXiv，自动挂到对应 arXiv 论文下
4. 标题相似度：Jaccard > 0.6
"""
from typing import List, Dict, Optional
from collections import defaultdict
from datetime import datetime
from models.paper import Paper, Event
from pipeline.clean import normalize_url, title_similarity, title_hash


def _normalize_arxiv_id(arxiv_id: str) -> str:
    """归一化 arXiv ID，去掉版本号
    '2410.12345v1' -> '2410.12345'
    'arxiv:2410.12345v2' -> '2410.12345'
    """
    if not arxiv_id:
        return ""
    s = arxiv_id.replace("arxiv:", "")
    # 去掉版本号
    if "v" in s:
        # 确保 v 后面是数字（避免误删 ID 里的 v）
        parts = s.split("v")
        if len(parts) == 2 and parts[1].isdigit():
            s = parts[0]
    return s


def _extract_arxiv_id_from_url(url: str) -> Optional[str]:
    """从 URL 里提取 arXiv ID"""
    if not url:
        return None
    # 匹配 arxiv.org/abs/2410.12345v1 或 arxiv.org/pdf/2410.12345
    import re
    m = re.search(r"arxiv\.org/(?:abs|pdf)/([\d.]+)(?:v\d+)?", url)
    if m:
        return m.group(1)
    return None


class EventAggregator:
    """把 Paper 列表聚合成 Event 列表"""

    def __init__(self, similarity_threshold: float = 0.6):
        self.similarity_threshold = similarity_threshold
        self.stats = {
            "arxiv_version_merged": 0,
            "arxiv_linked_attached": 0,
            "url_matched": 0,
            "title_matched": 0,
            "independent_l1_l2": 0,
        }

    def aggregate(self, papers: List[Paper]) -> List[Event]:
        """聚合"""
        self.stats = {
            "arxiv_version_merged": 0,
            "arxiv_linked_attached": 0,
            "url_matched": 0,
            "title_matched": 0,
            "independent_l1_l2": 0,
        }

        # 第一步：按归一化 arXiv ID 建立索引
        arxiv_index: Dict[str, Paper] = {}  # normalized_arxiv_id -> paper
        url_index: Dict[str, Paper] = {}

        l0_papers = [p for p in papers if p.source_level == "L0"]
        l1_l2_papers = [p for p in papers if p.source_level in ("L1", "L2")]

        # 第一步：合并 arXiv 版本号（v1/v2/v3 合并成同一个事件）
        arxiv_groups: Dict[str, List[Paper]] = defaultdict(list)
        for p in l0_papers:
            if p.source_type == "arxiv":
                base_id = _normalize_arxiv_id(p.source_id)
                arxiv_groups[base_id].append(p)
            else:
                # 非 arXiv 的 L0，单独成组
                arxiv_groups[p.id].append(p)

        # 合并 arXiv 版本：取最新的一篇作为主源，其他作为延伸
        events: Dict[str, Event] = {}
        for base_id, group in arxiv_groups.items():
            if len(group) > 1:
                self.stats["arxiv_version_merged"] += len(group) - 1
            # 按发布时间排序，最新的作为主源
            group.sort(key=lambda p: p.published_at, reverse=True)
            primary = group[0]
            extensions = group[1:]
            events[primary.id] = Event(
                id=primary.id,
                primary_paper=primary,
                extensions=extensions,
            )
            # 建立索引
            arxiv_index[base_id] = primary
            url_index[normalize_url(primary.url)] = primary

        # 第二步：处理 L1/L2
        for p in l1_l2_papers:
            matched = False

            # 2a：检查是否链到了 arXiv（从 raw_metadata 或 URL 本身提取）
            arxiv_id = None
            if p.raw_metadata and p.raw_metadata.get("arxiv_linked"):
                arxiv_id = _extract_arxiv_id_from_url(p.raw_metadata["arxiv_linked"])
            if not arxiv_id:
                arxiv_id = _extract_arxiv_id_from_url(p.url)

            if arxiv_id:
                base_id = _normalize_arxiv_id(arxiv_id)
                if base_id in arxiv_index:
                    orig = arxiv_index[base_id]
                    events[orig.id].extensions.append(p)
                    self.stats["arxiv_linked_attached"] += 1
                    continue

            # 2b：URL 精确匹配
            url = normalize_url(p.url)
            if url in url_index:
                orig = url_index[url]
                events[orig.id].extensions.append(p)
                self.stats["url_matched"] += 1
                continue

            # 2c：标题相似度匹配
            best_match = None
            best_sim = 0
            for event in events.values():
                sim = title_similarity(p.title, event.primary_paper.title)
                if sim > best_sim:
                    best_sim = sim
                    best_match = event

            if best_match and best_sim >= self.similarity_threshold:
                best_match.extensions.append(p)
                self.stats["title_matched"] += 1
                continue

            # 2d：独立事件
            events[p.id] = Event(
                id=p.id,
                primary_paper=p,
                extensions=[],
            )
            self.stats["independent_l1_l2"] += 1

        # 第三步：计算事件分
        result = []
        for event in events.values():
            event.score = self._compute_score(event)
            # 填充关系字段
            self._fill_relations(event)
            result.append(event)

        result.sort(key=lambda e: e.score, reverse=True)
        return result

    def _fill_relations(self, event: Event):
        """填充关系字段（作者、机构、数据集）"""
        all_papers = [event.primary_paper] + event.extensions
        authors = set()
        institutions = set()
        datasets = set()
        for p in all_papers:
            authors.update(p.authors)
            institutions.update(p.institutions)
            datasets.update(p.datasets)
        event.related_authors = list(authors)
        event.related_institutions = list(institutions)
        event.related_datasets = list(datasets)

    def _compute_score(self, event: Event) -> float:
        """计算事件重要性分"""
        days_ago = (datetime.utcnow() - event.primary_paper.published_at).days
        recency = max(0, 1 - days_ago / 7)

        level_map = {"L0": 1.0, "L1": 0.7, "L2": 0.3}
        source_level_score = level_map.get(event.primary_paper.source_level, 0.5)

        extension_score = min(0.5, len(event.extensions) * 0.1)

        score = 0.4 * recency + 0.4 * source_level_score + 0.2 * extension_score
        return round(score, 3)
