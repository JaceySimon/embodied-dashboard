"""
具身智能看板 - 数据模型
v1：统一 Paper 模型，后续聚合为 Event
"""
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field, HttpUrl
from enum import Enum


class SourceLevel(str, Enum):
    """信息源级别"""
    L0 = "L0"  # 一手原始（论文/tech report/代码/权重）
    L1 = "L1"  # 一手发布（公司博客/作者发言）
    L2 = "L2"  # 二手权威（媒体/分析）
    L3 = "L3"  # 三手噪音（默认不收）


class SourceType(str, Enum):
    """源类型"""
    ARXIV = "arxiv"
    OPENREVIEW = "openreview"
    HUGGINGFACE = "huggingface"
    GITHUB = "github"
    LAB_BLOG = "lab_blog"
    COMPANY_BLOG = "company_blog"
    X_THREAD = "x_thread"
    MEDIA = "media"


class Paper(BaseModel):
    """统一的论文/文章模型，所有采集器输出这个"""
    # 标识
    id: Optional[str] = None  # 内部 ID
    source_id: str  # 源 ID（如 arxiv:2410.12345）

    # 来源
    source_level: SourceLevel
    source_type: SourceType
    source_name: str  # 如 "arXiv cs.RO" / "Figure AI Blog"
    source_url: Optional[str] = None

    # 内容
    title: str
    abstract: Optional[str] = None
    authors: List[str] = Field(default_factory=list)
    institutions: List[str] = Field(default_factory=list)

    # 链接
    url: str  # 原文链接
    pdf_url: Optional[str] = None
    code_url: Optional[str] = None
    hf_url: Optional[str] = None

    # 时间
    published_at: datetime
    updated_at: Optional[datetime] = None

    # 分类（arXiv 原始分类）
    categories: List[str] = Field(default_factory=list)

    # 标签（LLM 打标后填）
    tags: List[str] = Field(default_factory=list)
    has_real_robot: Optional[bool] = None
    is_open_source: Optional[bool] = None
    robot_platforms: List[str] = Field(default_factory=list)  # 如 "UR5", "Franka", "Optimus"
    datasets: List[str] = Field(default_factory=list)

    # 去重
    title_hash: Optional[str] = None  # 归一化标题哈希
    title_minhash: Optional[str] = None  # v2 启用

    # 元数据
    raw_metadata: Optional[dict] = None

    class Config:
        use_enum_values = True


class Event(BaseModel):
    """聚合后的事件（同一件事的多个来源）"""
    id: str
    primary_paper: Paper  # 主源
    extensions: List[Paper] = Field(default_factory=list)  # 延伸源

    # 事件分
    score: float = 0.0
    score_breakdown: dict = Field(default_factory=dict)

    # 关系
    related_authors: List[str] = Field(default_factory=list)
    related_institutions: List[str] = Field(default_factory=list)
    related_datasets: List[str] = Field(default_factory=list)
    related_topics: List[str] = Field(default_factory=list)

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
