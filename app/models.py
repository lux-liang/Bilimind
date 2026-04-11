"""
BiliMind 知识树学习导航系统

数据模型定义
"""
from sqlalchemy import Column, Integer, Float, String, Text, DateTime, Boolean, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from datetime import datetime
from typing import Optional
from pydantic import BaseModel
from enum import Enum

Base = declarative_base()


# ==================== SQLAlchemy 模型 ====================

class VideoCache(Base):
    """内容缓存表（支持多平台：bilibili/xiaohongshu/zhihu）"""
    __tablename__ = 'video_cache'

    id = Column(Integer, primary_key=True, autoincrement=True)
    bvid = Column(String(20), unique=True, index=True, nullable=False)  # 通用source_id: bvid/note_id/answer_id
    cid = Column(Integer, nullable=True)
    source_type = Column(String(20), default='bilibili')  # bilibili/xiaohongshu/zhihu
    source_url = Column(String(1000), nullable=True)  # 原始URL
    title = Column(String(500), nullable=False)
    description = Column(Text, nullable=True)
    owner_name = Column(String(100), nullable=True)  # UP主名称
    owner_mid = Column(Integer, nullable=True)  # UP主ID
    
    # 内容
    content = Column(Text, nullable=True)  # 摘要/字幕文本
    content_source = Column(String(20), nullable=True)  # ai_summary / subtitle / basic_info
    outline_json = Column(JSON, nullable=True)  # 分段提纲
    
    # 元信息
    duration = Column(Integer, nullable=True)  # 视频时长（秒）
    pic_url = Column(String(500), nullable=True)  # 封面URL
    tags = Column(JSON, nullable=True)  # B站标签列表

    # LLM 生成
    summary = Column(Text, nullable=True)  # LLM 生成的视频摘要

    # 处理状态
    is_processed = Column(Boolean, default=False)  # 是否已处理并加入向量库
    process_error = Column(Text, nullable=True)  # 处理错误信息
    extraction_status = Column(String(20), default='pending')  # pending/done/failed
    knowledge_node_count = Column(Integer, default=0)  # 关联知识点数量
    session_id = Column(String(64), index=True, nullable=True)  # 用户隔离

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class UserSession(Base):
    """用户会话表"""
    __tablename__ = 'user_sessions'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(64), unique=True, index=True, nullable=False)
    
    # B站用户信息
    bili_mid = Column(Integer, nullable=True)  # B站用户ID
    bili_uname = Column(String(100), nullable=True)  # B站用户名
    bili_face = Column(String(500), nullable=True)  # 头像URL
    
    # Cookie 信息（加密存储更安全，这里简化处理）
    sessdata = Column(Text, nullable=True)
    bili_jct = Column(Text, nullable=True)
    dedeuserid = Column(String(50), nullable=True)
    
    # 状态
    is_valid = Column(Boolean, default=True)
    last_active_at = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)


class FavoriteFolder(Base):
    """收藏夹记录表"""
    __tablename__ = 'favorite_folders'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(64), index=True, nullable=False)
    
    # B站收藏夹信息  
    media_id = Column(Integer, nullable=False)  # 收藏夹ID
    fid = Column(Integer, nullable=True)  # 原始ID
    title = Column(String(200), nullable=False)
    media_count = Column(Integer, default=0)  # 视频数量
    
    # 状态
    is_selected = Column(Boolean, default=True)  # 是否选中用于知识库
    last_sync_at = Column(DateTime, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class FavoriteVideo(Base):
    """收藏夹-视频关联表"""
    __tablename__ = 'favorite_videos'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    folder_id = Column(Integer, index=True, nullable=False)  # 关联 FavoriteFolder.id
    bvid = Column(String(20), index=True, nullable=False)
    
    # 是否选中（用户可以取消选中某些视频）
    is_selected = Column(Boolean, default=True)

    created_at = Column(DateTime, default=datetime.utcnow)


# ==================== 知识树新增模型 ====================

class Segment(Base):
    """视频片段表 — 带时间戳的文本片段"""
    __tablename__ = 'segments'

    id = Column(Integer, primary_key=True, autoincrement=True)
    video_bvid = Column(String(20), index=True, nullable=False)
    segment_index = Column(Integer, nullable=False)
    start_time = Column(Float, nullable=True)   # 开始时间(秒)
    end_time = Column(Float, nullable=True)     # 结束时间(秒)
    raw_text = Column(Text, nullable=False)
    cleaned_text = Column(Text, nullable=True)
    summary = Column(Text, nullable=True)
    source_type = Column(String(20), nullable=True)  # subtitle / asr / basic
    confidence = Column(Float, default=1.0)
    extraction_status = Column(String(20), default='pending')  # pending/done/failed
    session_id = Column(String(64), index=True, nullable=True)  # 用户隔离
    knowledge_density = Column(Float, nullable=True)  # 知识密度分数
    is_peak = Column(Boolean, default=False)  # 是否为知识峰值片段
    created_at = Column(DateTime, default=datetime.utcnow)


class KnowledgeNode(Base):
    """知识节点表"""
    __tablename__ = 'knowledge_nodes'

    id = Column(Integer, primary_key=True, autoincrement=True)
    node_type = Column(String(20), nullable=False)       # topic/concept/method/tool/task
    name = Column(String(200), nullable=False)
    normalized_name = Column(String(200), index=True)
    aliases = Column(JSON, default=list)
    definition = Column(Text, nullable=True)
    difficulty = Column(Integer, default=1)              # 1-5
    main_topic_id = Column(Integer, nullable=True)       # 主归属 topic 的 node_id
    confidence = Column(Float, default=0.5)
    source_count = Column(Integer, default=1)
    review_status = Column(String(20), default='auto')   # auto/approved/rejected/pending_review
    session_id = Column(String(64), index=True, nullable=True)  # 用户隔离
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class KnowledgeEdge(Base):
    """知识关系表"""
    __tablename__ = 'knowledge_edges'

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_node_id = Column(Integer, index=True, nullable=False)
    target_node_id = Column(Integer, index=True, nullable=False)
    relation_type = Column(String(30), nullable=False)   # prerequisite_of/part_of/related_to/explains/supports/mentions
    weight = Column(Float, default=1.0)
    confidence = Column(Float, default=0.5)
    evidence_segment_id = Column(Integer, nullable=True)
    evidence_video_bvid = Column(String(20), nullable=True)
    session_id = Column(String(64), index=True, nullable=True)  # 用户隔离
    created_at = Column(DateTime, default=datetime.utcnow)


class NodeSegmentLink(Base):
    """知识节点-片段关联表"""
    __tablename__ = 'node_segment_links'

    id = Column(Integer, primary_key=True, autoincrement=True)
    node_id = Column(Integer, index=True, nullable=False)
    segment_id = Column(Integer, index=True, nullable=False)
    video_bvid = Column(String(20), index=True)
    relation = Column(String(20), default='mentions')    # mentions/explains/demonstrates
    confidence = Column(Float, default=0.5)
    session_id = Column(String(64), index=True, nullable=True)  # 用户隔离


class GameScore(Base):
    """知识预测游戏得分表"""
    __tablename__ = 'game_scores'

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(64), index=True, nullable=False)
    score = Column(Integer, default=0)
    total_challenges = Column(Integer, default=0)
    correct_count = Column(Integer, default=0)
    streak = Column(Integer, default=0)
    best_streak = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SRSRecord(Base):
    """间隔重复记录表"""
    __tablename__ = 'srs_records'

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(64), index=True, nullable=False)
    node_id = Column(Integer, index=True, nullable=False)
    easiness_factor = Column(Float, default=2.5)
    interval_days = Column(Float, default=1.0)
    repetitions = Column(Integer, default=0)
    next_review_date = Column(DateTime, nullable=True)
    last_review_date = Column(DateTime, nullable=True)
    implicit_review = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ==================== 知映 ZhiYing 知识编译模型 ====================

class Concept(Base):
    """概念表 — 知识编译的一级单元"""
    __tablename__ = 'concepts'

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(64), index=True, nullable=True)
    name = Column(String(200), nullable=False)
    normalized_name = Column(String(200), index=True)
    definition = Column(Text, nullable=True)
    difficulty = Column(Integer, default=1)  # 1-5
    source_count = Column(Integer, default=1)  # 被多少个片段提到
    video_count = Column(Integer, default=1)  # 出现在多少个视频中
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Claim(Base):
    """论断表 — 概念下的具体知识声明，锚定到视频时间戳"""
    __tablename__ = 'claims'

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(64), index=True, nullable=True)
    concept_id = Column(Integer, index=True, nullable=False)  # FK → Concept
    statement = Column(Text, nullable=False)  # 论断文本
    claim_type = Column(String(30), default='explanation')  # definition/explanation/example/comparison/warning
    confidence = Column(Float, default=0.5)
    segment_id = Column(Integer, index=True, nullable=True)  # FK → Segment
    video_bvid = Column(String(20), index=True, nullable=True)
    start_time = Column(Float, nullable=True)  # 秒
    end_time = Column(Float, nullable=True)
    raw_text = Column(Text, nullable=True)  # 原始字幕片段
    created_at = Column(DateTime, default=datetime.utcnow)


class ConceptRelation(Base):
    """概念关系表 — 前置/相关/包含"""
    __tablename__ = 'concept_relations'

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(64), index=True, nullable=True)
    source_concept_id = Column(Integer, index=True, nullable=False)
    target_concept_id = Column(Integer, index=True, nullable=False)
    relation_type = Column(String(30), nullable=False)  # prerequisite_of / related_to / part_of
    confidence = Column(Float, default=0.5)
    created_at = Column(DateTime, default=datetime.utcnow)


class CrossVideoAlignment(Base):
    """跨视频对齐表 — 同一概念在不同视频中的讲法对比"""
    __tablename__ = 'cross_video_alignments'

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(64), index=True, nullable=True)
    concept_id = Column(Integer, index=True, nullable=False)
    claim_a_id = Column(Integer, nullable=False)
    claim_b_id = Column(Integer, nullable=False)
    alignment_type = Column(String(30), nullable=False)  # consistent / complementary / perspective_diff
    explanation = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class UserMastery(Base):
    """用户知识掌握度"""
    __tablename__ = 'user_mastery'

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(64), index=True, nullable=False)
    concept_id = Column(Integer, index=True, nullable=False)
    mastery_level = Column(Integer, default=0)  # 0=未学 1=了解 2=理解 3=掌握 4=精通 5=专家
    last_reviewed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ==================== Pydantic 模型 (API 用) ====================

class ContentSource(str, Enum):
    """内容来源"""
    AI_SUMMARY = "ai_summary"
    SUBTITLE = "subtitle"
    BASIC_INFO = "basic_info"
    ASR = "asr"


class NodeType(str, Enum):
    """知识节点类型"""
    TOPIC = "topic"
    CONCEPT = "concept"
    METHOD = "method"
    TOOL = "tool"
    TASK = "task"


class RelationType(str, Enum):
    """知识关系类型"""
    PREREQUISITE_OF = "prerequisite_of"
    PART_OF = "part_of"
    RELATED_TO = "related_to"
    EXPLAINS = "explains"
    SUPPORTS = "supports"
    MENTIONS = "mentions"
    RECOMMENDS_NEXT = "recommends_next"
    VIDEO_FOR = "video_for"


class ReviewStatus(str, Enum):
    """审核状态"""
    AUTO = "auto"
    APPROVED = "approved"
    REJECTED = "rejected"
    PENDING_REVIEW = "pending_review"


class VideoInfo(BaseModel):
    """视频信息"""
    bvid: str
    cid: Optional[int] = None
    title: str
    description: Optional[str] = None
    owner_name: Optional[str] = None
    owner_mid: Optional[int] = None
    duration: Optional[int] = None
    pic_url: Optional[str] = None


class SourceType(str, Enum):
    """内容平台来源"""
    BILIBILI = "bilibili"
    XIAOHONGSHU = "xiaohongshu"
    ZHIHU = "zhihu"


class VideoContent(BaseModel):
    """内容（含摘要，支持多平台）"""
    bvid: str  # 通用source_id
    title: str
    content: str
    source: ContentSource
    source_type: SourceType = SourceType.BILIBILI
    outline: Optional[list] = None
    session_id: Optional[str] = None


class QRCodeResponse(BaseModel):
    """二维码响应"""
    qrcode_key: str
    qrcode_url: str
    qrcode_image_base64: str


class LoginStatusResponse(BaseModel):
    """登录状态响应"""
    status: str  # waiting / scanned / confirmed / expired
    message: str
    user_info: Optional[dict] = None
    session_id: Optional[str] = None


class FavoriteFolderInfo(BaseModel):
    """收藏夹信息"""
    media_id: int
    title: str
    media_count: int
    is_selected: bool = True
    is_default: Optional[bool] = None


class ChatRequest(BaseModel):
    """对话请求"""
    question: str
    session_id: Optional[str] = None
    folder_ids: Optional[list[int]] = None  # 指定收藏夹，None 表示全部


class ChatResponse(BaseModel):
    """对话响应"""
    answer: str
    sources: list[dict]  # 来源视频列表


# ==================== 知识树 API 模型 ====================

class SegmentInfo(BaseModel):
    """片段信息"""
    id: int
    video_bvid: str
    segment_index: int
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    text: str
    summary: Optional[str] = None
    source_type: Optional[str] = None

    @property
    def time_label(self) -> str:
        if self.start_time is not None and self.end_time is not None:
            return f"{_fmt_time(self.start_time)}-{_fmt_time(self.end_time)}"
        return ""


class TreeNodeInfo(BaseModel):
    """知识树节点"""
    id: int
    name: str
    node_type: str
    difficulty: int = 1
    definition: Optional[str] = None
    video_count: int = 0
    node_count: int = 0
    confidence: float = 0.5
    is_reference: bool = False
    children: list["TreeNodeInfo"] = []


class NodeDetailInfo(BaseModel):
    """节点详情"""
    id: int
    name: str
    node_type: str
    definition: Optional[str] = None
    difficulty: int = 1
    confidence: float = 0.5
    source_count: int = 0
    review_status: str = "auto"
    aliases: list[str] = []
    main_topic: Optional[dict] = None
    related_topics: list[dict] = []
    prerequisites: list[dict] = []
    successors: list[dict] = []
    related_nodes: list[dict] = []
    videos: list[dict] = []
    segments: list[dict] = []


class VideoDetailInfo(BaseModel):
    """视频详情"""
    bvid: str
    title: str
    description: Optional[str] = None
    owner_name: Optional[str] = None
    duration: Optional[int] = None
    pic_url: Optional[str] = None
    summary: Optional[str] = None
    knowledge_nodes: list[dict] = []
    segments: list[dict] = []
    tree_positions: list[dict] = []


class DifficultyStage(str, Enum):
    """难度阶段（前端筛选用）"""
    BEGINNER = "beginner"      # 入门: difficulty 1-2
    INTERMEDIATE = "intermediate"  # 进阶: difficulty 3-4
    ADVANCED = "advanced"      # 实战: difficulty 5

    @classmethod
    def difficulty_range(cls, stage: "DifficultyStage") -> tuple[int, int]:
        return {
            cls.BEGINNER: (1, 2),
            cls.INTERMEDIATE: (3, 4),
            cls.ADVANCED: (5, 5),
        }[stage]


class LearningPathStepInfo(BaseModel):
    """学习路径步骤"""
    order: int
    node_id: int
    name: str
    node_type: str
    difficulty: int = 1
    definition: Optional[str] = None
    confidence: float = 0.5
    reason: str = ""
    is_optional: bool = False
    has_videos: bool = False
    video_count: int = 0
    videos: list[dict] = []


class LearningPathInfo(BaseModel):
    """学习路径完整信息"""
    target: dict
    mode: str
    steps: list[LearningPathStepInfo] = []
    total_steps: int = 0
    estimated_videos: int = 0


class ChatEvidenceInfo(BaseModel):
    """问答证据信息 — 增强版，含图谱节点和片段追溯"""
    answer: str
    sources: list[dict] = []
    related_nodes: list[dict] = []
    related_segments: list[dict] = []
    route_type: str = "vector"  # vector / graph / path / hybrid


def _fmt_time(seconds: float) -> str:
    """格式化秒为 MM:SS"""
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"
