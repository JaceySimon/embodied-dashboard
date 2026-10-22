"""
具身智能看板 - 采集器基类
"""
from abc import ABC, abstractmethod
from typing import List
from models.paper import Paper


class BaseCollector(ABC):
    """所有采集器的基类"""
    source_name: str = ""
    source_level: str = ""
    source_type: str = ""

    @abstractmethod
    def collect(self, lookback_days: int = 7) -> List[Paper]:
        """采集最近 N 天的内容，返回 Paper 列表"""
        pass
