"""
BiliMind 知识树学习导航系统

核心配置模块
"""
from pydantic_settings import BaseSettings
from pydantic import Field, AliasChoices
from typing import Optional
import os


class Settings(BaseSettings):
    """应用配置"""

    # OpenAI / LLM 配置
    openai_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("DASHSCOPE_API_KEY", "OPENAI_API_KEY"),
    )
    openai_base_url: str = Field(default="https://api.openai.com/v1", env="OPENAI_BASE_URL")
    llm_model: str = Field(default="gpt-4-turbo", env="LLM_MODEL")
    embedding_model: str = Field(default="text-embedding-3-small", env="EMBEDDING_MODEL")

    # DashScope ASR
    dashscope_base_url: str = Field(
        default="https://dashscope.aliyuncs.com/api/v1",
        env="DASHSCOPE_BASE_URL"
    )
    asr_model: str = Field(default="paraformer-v2", env="ASR_MODEL")
    asr_timeout: int = Field(default=600, env="ASR_TIMEOUT")
    asr_model_local: str = Field(default="paraformer-realtime-v2", env="ASR_MODEL_LOCAL")
    asr_input_format: str = Field(default="pcm", env="ASR_INPUT_FORMAT")

    # 应用配置
    app_host: str = Field(default="0.0.0.0", env="APP_HOST")
    app_port: int = Field(default=8000, env="APP_PORT")
    debug: bool = Field(default=True, env="DEBUG")

    # 数据库
    database_url: str = Field(
        default="sqlite+aiosqlite:///./data/bilimind.db",
        env="DATABASE_URL"
    )

    # ChromaDB
    chroma_persist_directory: str = Field(
        default="./data/chroma_db",
        env="CHROMA_PERSIST_DIRECTORY"
    )

    # 知识图谱
    graph_persist_path: str = Field(
        default="./data/graph.json",
        env="GRAPH_PERSIST_PATH"
    )

    # 知识抽取
    extraction_min_confidence: float = Field(default=0.3, env="EXTRACTION_MIN_CONFIDENCE")
    tree_min_confidence: float = Field(default=0.4, env="TREE_MIN_CONFIDENCE")
    extraction_segment_merge_seconds: float = Field(default=30.0, env="EXTRACTION_SEGMENT_MERGE_SECONDS")

    # 轻量模型
    ml_artifact_dir: str = Field(default="./data/models", env="MODEL_ARTIFACT_DIR")
    evidence_ranker_model_path: str = Field(default="./data/models/evidence_ranker.json", env="EVIDENCE_RANKER_MODEL_PATH")
    organizer_classifier_model_path: str = Field(default="./data/models/organizer_classifier.json", env="ORGANIZER_CLASSIFIER_MODEL_PATH")
    evidence_ranker_enabled: bool = Field(default=True, env="EVIDENCE_RANKER_ENABLED")
    organizer_classifier_enabled: bool = Field(default=True, env="ORGANIZER_CLASSIFIER_ENABLED")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


# 全局配置实例
settings = Settings()


def ensure_directories():
    """确保必要的目录存在"""
    dirs = [
        "data",
        settings.chroma_persist_directory,
        settings.ml_artifact_dir,
        "logs"
    ]
    for d in dirs:
        os.makedirs(d, exist_ok=True)
