"""
BiliMind 知识树学习导航系统

统一搜索路由 — 关键词 + 语义 + 图谱三路混合
"""
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Query, Depends
from loguru import logger
from sqlalchemy import select, or_, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import (
    KnowledgeNode, Segment, VideoCache, NodeSegmentLink, _fmt_time,
)
from app.services.rag import RAGService
from app.services.graph_store import GraphStore
from app.config import settings

router = APIRouter(prefix="/search", tags=["搜索"])

_rag_service: Optional[RAGService] = None
_graph_store: Optional[GraphStore] = None


def _get_rag() -> RAGService:
    global _rag_service
    if _rag_service is None:
        _rag_service = RAGService()
    return _rag_service


def _get_graph() -> GraphStore:
    global _graph_store
    if _graph_store is None:
        _graph_store = GraphStore(graph_path=settings.graph_persist_path)
        _graph_store.load_json()
    return _graph_store


@router.get("")
async def unified_search(
    q: str = Query(..., min_length=1, description="搜索关键词"),
    type: str = Query("all", description="all / nodes / videos / segments"),
    limit: int = Query(20, le=50),
    db: AsyncSession = Depends(get_db),
):
    """
    统一搜索：关键词 + 语义 + 图谱混合

    type=all: 合并所有结果
    type=nodes: 只搜知识节点
    type=videos: 只搜视频
    type=segments: 只搜片段（语义检索）
    """
    results = {
        "query": q,
        "type": type,
        "nodes": [],
        "videos": [],
        "segments": [],
    }

    if type in ("all", "nodes"):
        results["nodes"] = await _search_nodes(q, limit, db)

    if type in ("all", "videos"):
        results["videos"] = await _search_videos(q, limit, db)

    if type in ("all", "segments"):
        results["segments"] = await _search_segments(q, min(limit, 10), db)

    return results


@router.get("/nodes")
async def search_nodes(
    q: str = Query(..., min_length=1),
    limit: int = Query(20, le=50),
    db: AsyncSession = Depends(get_db),
):
    """搜索知识节点"""
    return await _search_nodes(q, limit, db)


@router.get("/videos")
async def search_videos(
    q: str = Query(..., min_length=1),
    limit: int = Query(20, le=50),
    db: AsyncSession = Depends(get_db),
):
    """搜索视频"""
    return await _search_videos(q, limit, db)


@router.get("/segments")
async def search_segments(
    q: str = Query(..., min_length=1),
    limit: int = Query(10, le=20),
    db: AsyncSession = Depends(get_db),
):
    """搜索片段（语义检索）"""
    return await _search_segments(q, limit, db)


# ==================== 搜索实现 ====================

async def _search_nodes(q: str, limit: int, db: AsyncSession) -> list[dict]:
    """关键词搜索知识节点 + 图谱名称匹配"""
    # SQLite LIKE 搜索
    pattern = f"%{q}%"
    result = await db.execute(
        select(KnowledgeNode)
        .where(
            KnowledgeNode.review_status != "rejected",
            or_(
                KnowledgeNode.name.ilike(pattern),
                KnowledgeNode.normalized_name.ilike(pattern),
                KnowledgeNode.definition.ilike(pattern),
            )
        )
        .order_by(KnowledgeNode.source_count.desc())
        .limit(limit)
    )
    nodes = result.scalars().all()

    items = []
    for n in nodes:
        vid_count = await db.scalar(
            select(func.count(func.distinct(NodeSegmentLink.video_bvid)))
            .where(NodeSegmentLink.node_id == n.id)
        )
        items.append({
            "id": n.id,
            "name": n.name,
            "node_type": n.node_type,
            "difficulty": n.difficulty,
            "definition": n.definition,
            "confidence": n.confidence,
            "source_count": n.source_count,
            "video_count": vid_count or 0,
        })

    return items


async def _search_videos(q: str, limit: int, db: AsyncSession) -> list[dict]:
    """关键词搜索视频"""
    pattern = f"%{q}%"
    result = await db.execute(
        select(VideoCache)
        .where(
            or_(
                VideoCache.title.ilike(pattern),
                VideoCache.description.ilike(pattern),
                VideoCache.owner_name.ilike(pattern),
            )
        )
        .limit(limit)
    )
    videos = result.scalars().all()

    items = []
    for v in videos:
        kn_count = await db.scalar(
            select(func.count(func.distinct(NodeSegmentLink.node_id)))
            .where(NodeSegmentLink.video_bvid == v.bvid)
        )
        items.append({
            "bvid": v.bvid,
            "title": v.title,
            "description": (v.description or "")[:200],
            "owner_name": v.owner_name,
            "duration": v.duration,
            "pic_url": v.pic_url,
            "knowledge_node_count": kn_count or 0,
            "url": f"https://www.bilibili.com/video/{v.bvid}",
        })

    return items


async def _search_segments(q: str, limit: int, db: AsyncSession) -> list[dict]:
    """语义搜索片段（通过 ChromaDB 向量检索）"""
    try:
        rag = _get_rag()
        docs = rag.search(q, k=limit)
    except Exception as e:
        logger.warning(f"Semantic search failed: {e}")
        docs = []

    items = []
    for doc in docs:
        meta = doc.metadata or {}
        bvid = meta.get("bvid", "")
        items.append({
            "bvid": bvid,
            "title": meta.get("title", ""),
            "content_preview": doc.page_content[:300],
            "chunk_index": meta.get("chunk_index"),
            "url": meta.get("url", f"https://www.bilibili.com/video/{bvid}"),
        })

    return items
