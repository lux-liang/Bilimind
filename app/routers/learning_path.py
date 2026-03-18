"""
BiliMind 知识树学习导航系统

学习路径路由 — 独立的学习路径 API

支持:
- 按目标主题名搜索 → 自动生成学习路径
- 按目标节点 ID → 精确生成学习路径
- 三种模式: beginner / standard / quick
"""
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Query, Depends
from loguru import logger
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import (
    KnowledgeNode, NodeSegmentLink, Segment, VideoCache, _fmt_time,
)
from app.services.graph_store import GraphStore
from app.services.path_recommender import PathRecommender
from app.config import settings

router = APIRouter(prefix="/learning-path", tags=["学习路径"])

_graph_store: Optional[GraphStore] = None


def _get_graph_store() -> GraphStore:
    global _graph_store
    if _graph_store is None:
        _graph_store = GraphStore(graph_path=settings.graph_persist_path)
        _graph_store.load_json()
    return _graph_store


@router.get("/search")
async def search_target_topics(
    q: str = Query(..., min_length=1, description="搜索目标知识点"),
    limit: int = Query(10, le=30),
    db: AsyncSession = Depends(get_db),
):
    """搜索可作为学习目标的知识节点"""
    pattern = f"%{q}%"
    result = await db.execute(
        select(KnowledgeNode)
        .where(
            KnowledgeNode.review_status != "rejected",
            KnowledgeNode.name.ilike(pattern),
        )
        .order_by(KnowledgeNode.source_count.desc())
        .limit(limit)
    )
    nodes = result.scalars().all()
    return [
        {
            "id": n.id,
            "name": n.name,
            "node_type": n.node_type,
            "difficulty": n.difficulty,
            "definition": n.definition,
            "confidence": n.confidence,
            "source_count": n.source_count,
        }
        for n in nodes
    ]


@router.get("/generate")
async def generate_learning_path(
    target: str = Query(None, description="目标知识点名称（和 node_id 二选一）"),
    node_id: int = Query(None, description="目标节点 ID（和 target 二选一）"),
    mode: str = Query("standard", description="beginner / standard / quick"),
    known: Optional[str] = Query(None, description="已掌握节点 ID 列表，逗号分隔"),
    db: AsyncSession = Depends(get_db),
):
    """
    生成学习路径

    支持两种输入:
    - node_id: 精确指定目标节点
    - target: 按名称搜索目标节点（取最佳匹配）

    返回包含:
    - 路径步骤（带推荐理由）
    - 每步对应的视频和时间片段
    - 为什么这样推荐
    """
    if not target and node_id is None:
        raise HTTPException(status_code=400, detail="请提供 target 或 node_id")

    if mode not in ("beginner", "standard", "quick"):
        mode = "standard"

    gs = _get_graph_store()
    if gs.node_count() == 0:
        await gs.load_from_db(db)

    # 确定目标节点
    target_id = node_id
    if target_id is None:
        # 按名称搜索
        results = gs.search_nodes_by_name(target, limit=5)
        if not results:
            # fallback 到 DB
            pattern = f"%{target}%"
            db_result = await db.execute(
                select(KnowledgeNode)
                .where(KnowledgeNode.name.ilike(pattern))
                .order_by(KnowledgeNode.source_count.desc())
                .limit(1)
            )
            node = db_result.scalar_one_or_none()
            if node:
                target_id = node.id
            else:
                raise HTTPException(status_code=404, detail=f"未找到知识点: {target}")
        else:
            target_id = results[0]["id"]

    if not gs.has_node(target_id):
        raise HTTPException(status_code=404, detail="节点不存在于知识图谱中")

    # 解析已知节点
    known_ids = []
    if known:
        try:
            known_ids = [int(x.strip()) for x in known.split(",") if x.strip()]
        except ValueError:
            pass

    # 生成路径
    recommender = PathRecommender(gs)
    result = recommender.recommend_path(target_id, mode=mode, known_node_ids=known_ids)

    # 为每个步骤填充视频和片段信息
    for step in result.get("steps", []):
        nid = step["node_id"]
        await _fill_step_videos(step, nid, db)

    return result


@router.get("/topics")
async def get_popular_topics(
    limit: int = Query(20, le=50),
    db: AsyncSession = Depends(get_db),
):
    """获取热门学习目标（按 source_count 排序）"""
    result = await db.execute(
        select(KnowledgeNode)
        .where(
            KnowledgeNode.review_status != "rejected",
            KnowledgeNode.source_count >= 2,
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
            "source_count": n.source_count,
            "video_count": vid_count or 0,
        })
    return items


# ==================== 辅助函数 ====================

async def _fill_step_videos(step: dict, node_id: int, db: AsyncSession) -> None:
    """为路径步骤填充视频和片段信息"""
    # 统计视频数
    vid_count = await db.scalar(
        select(func.count(func.distinct(NodeSegmentLink.video_bvid)))
        .where(NodeSegmentLink.node_id == node_id)
    )
    step["has_videos"] = (vid_count or 0) > 0
    step["video_count"] = vid_count or 0

    # 获取代表性视频（最多 2 个）
    links = await db.execute(
        select(NodeSegmentLink.video_bvid)
        .where(NodeSegmentLink.node_id == node_id)
        .distinct()
        .limit(2)
    )
    bvids = [row[0] for row in links.fetchall()]
    step["videos"] = []

    for bvid in bvids:
        vc = await db.execute(select(VideoCache).where(VideoCache.bvid == bvid))
        video = vc.scalar_one_or_none()
        if not video:
            continue

        # 获取该节点在该视频中的片段
        seg_links = await db.execute(
            select(NodeSegmentLink.segment_id)
            .where(NodeSegmentLink.node_id == node_id, NodeSegmentLink.video_bvid == bvid)
        )
        seg_ids = [r[0] for r in seg_links.fetchall()]
        segs = []
        if seg_ids:
            seg_result = await db.execute(
                select(Segment).where(Segment.id.in_(seg_ids)).order_by(Segment.start_time)
            )
            for seg in seg_result.scalars().all():
                segs.append({
                    "id": seg.id,
                    "text": (seg.cleaned_text or seg.raw_text or "")[:200],
                    "time_label": f"{_fmt_time(seg.start_time)}-{_fmt_time(seg.end_time)}"
                                 if seg.start_time is not None else "",
                    "url": f"https://www.bilibili.com/video/{bvid}?t={int(seg.start_time)}"
                           if seg.start_time is not None else None,
                })

        step["videos"].append({
            "bvid": video.bvid,
            "title": video.title,
            "duration": video.duration,
            "url": f"https://www.bilibili.com/video/{video.bvid}",
            "segments": segs,
        })
