"""
BiliMind 知识树学习导航系统

知识树路由 — 树结构、节点详情、视频详情
"""
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Query, Depends
from loguru import logger
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import (
    KnowledgeNode, KnowledgeEdge, NodeSegmentLink, Segment, VideoCache,
    TreeNodeInfo, NodeDetailInfo, VideoDetailInfo, SegmentInfo, _fmt_time,
)
from app.services.graph_store import GraphStore
from app.services.tree_builder import TreeBuilder
from app.services.path_recommender import PathRecommender
from app.config import settings

router = APIRouter(prefix="/tree", tags=["知识树"])

# 全局图存储和树构建器实例
_graph_store: Optional[GraphStore] = None
_tree_builder: Optional[TreeBuilder] = None


def get_graph_store() -> GraphStore:
    global _graph_store
    if _graph_store is None:
        _graph_store = GraphStore(graph_path=settings.graph_persist_path)
        _graph_store.load_json()
    return _graph_store


def get_tree_builder() -> TreeBuilder:
    global _tree_builder
    if _tree_builder is None:
        _tree_builder = TreeBuilder(get_graph_store())
    return _tree_builder


def get_path_recommender() -> PathRecommender:
    return PathRecommender(get_graph_store())


@router.get("")
async def get_knowledge_tree(
    min_confidence: Optional[float] = Query(None, description="最低置信度"),
    topic_id: Optional[int] = Query(None, description="按主题筛选（只返回该主题子树）"),
    stage: Optional[str] = Query(None, description="按难度阶段筛选: beginner/intermediate/advanced"),
    db: AsyncSession = Depends(get_db),
):
    """获取完整知识树结构（支持主题筛选和阶段筛选）"""
    try:
        gs = get_graph_store()
        # 如果图为空，从 DB 加载
        if gs.node_count() == 0:
            await gs.load_from_db(db)

        builder = get_tree_builder()
        tree_data = builder.build_tree(min_confidence=min_confidence)

        # 主题筛选：只返回指定 topic 的子树
        if topic_id is not None:
            tree_data["tree"] = [
                t for t in tree_data["tree"]
                if t.get("id") == topic_id
            ]

        # 阶段筛选：按难度范围过滤节点
        if stage and stage in ("beginner", "intermediate", "advanced"):
            from app.models import DifficultyStage
            diff_range = DifficultyStage.difficulty_range(DifficultyStage(stage))
            tree_data["tree"] = _filter_tree_by_difficulty(tree_data["tree"], diff_range)

        # 填充每个节点的 video_count
        await _fill_video_counts(tree_data["tree"], db)

        return tree_data
    except Exception as e:
        logger.error(f"获取知识树失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/topics")
async def get_topics(db: AsyncSession = Depends(get_db)):
    """获取一级主题列表"""
    try:
        result = await db.execute(
            select(KnowledgeNode).where(KnowledgeNode.node_type == "topic")
            .order_by(KnowledgeNode.source_count.desc())
        )
        topics = result.scalars().all()
        return [
            {
                "id": t.id,
                "name": t.name,
                "definition": t.definition,
                "difficulty": t.difficulty,
                "source_count": t.source_count,
                "confidence": t.confidence,
            }
            for t in topics
        ]
    except Exception as e:
        logger.error(f"获取主题列表失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/node/{node_id}")
async def get_node_detail(node_id: int, db: AsyncSession = Depends(get_db)):
    """获取知识节点详情"""
    result = await db.execute(
        select(KnowledgeNode).where(KnowledgeNode.id == node_id)
    )
    node = result.scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=404, detail="节点不存在")

    gs = get_graph_store()
    if gs.node_count() == 0:
        await gs.load_from_db(db)

    # 主归属
    main_topic = None
    if node.main_topic_id:
        topic_result = await db.execute(
            select(KnowledgeNode).where(KnowledgeNode.id == node.main_topic_id)
        )
        topic = topic_result.scalar_one_or_none()
        if topic:
            main_topic = {"id": topic.id, "name": topic.name}

    # 关系
    prerequisites = gs.get_prerequisites(node_id)
    successors = gs.get_successors(node_id)
    related = gs.get_related(node_id)

    # 关联主题
    related_topics = []
    part_of_targets = gs.get_neighbors(node_id, relation_type="part_of", direction="out")
    for t in part_of_targets:
        if t.get("node_type") == "topic" and t["id"] != (node.main_topic_id or -1):
            related_topics.append({"id": t["id"], "name": t.get("name", "")})

    # 关联视频和片段
    links_result = await db.execute(
        select(NodeSegmentLink).where(NodeSegmentLink.node_id == node_id)
    )
    links = links_result.scalars().all()

    # 收集视频 bvid
    video_bvids = list(set(link.video_bvid for link in links if link.video_bvid))
    videos = []
    if video_bvids:
        vids_result = await db.execute(
            select(VideoCache).where(VideoCache.bvid.in_(video_bvids))
        )
        for vc in vids_result.scalars().all():
            # 获取该视频关联的片段
            vid_segments = []
            for link in links:
                if link.video_bvid == vc.bvid:
                    seg_result = await db.execute(
                        select(Segment).where(Segment.id == link.segment_id)
                    )
                    seg = seg_result.scalar_one_or_none()
                    if seg:
                        vid_segments.append({
                            "id": seg.id,
                            "start_time": seg.start_time,
                            "end_time": seg.end_time,
                            "text": (seg.cleaned_text or seg.raw_text)[:200],
                            "time_label": f"{_fmt_time(seg.start_time)}-{_fmt_time(seg.end_time)}" if seg.start_time is not None else "",
                        })

            videos.append({
                "bvid": vc.bvid,
                "title": vc.title,
                "owner_name": vc.owner_name,
                "pic_url": vc.pic_url,
                "duration": vc.duration,
                "segments": vid_segments,
                "url": f"https://www.bilibili.com/video/{vc.bvid}",
            })

    # 树中位置
    builder = get_tree_builder()
    tree_position = builder.get_node_tree_position(node_id)

    return {
        "id": node.id,
        "name": node.name,
        "node_type": node.node_type,
        "definition": node.definition,
        "difficulty": node.difficulty,
        "confidence": node.confidence,
        "source_count": node.source_count,
        "review_status": node.review_status,
        "aliases": node.aliases or [],
        "main_topic": main_topic,
        "related_topics": related_topics,
        "prerequisites": [{"id": n["id"], "name": n.get("name", ""), "difficulty": n.get("difficulty", 1)} for n in prerequisites],
        "successors": [{"id": n["id"], "name": n.get("name", ""), "difficulty": n.get("difficulty", 1)} for n in successors],
        "related_nodes": [{"id": n["id"], "name": n.get("name", ""), "node_type": n.get("node_type", "")} for n in related],
        "videos": videos,
        "tree_position": tree_position,
    }


@router.get("/video/{bvid}")
async def get_video_detail(bvid: str, db: AsyncSession = Depends(get_db)):
    """获取视频详情（知识点 + 时间片段 + 树中位置）"""
    result = await db.execute(
        select(VideoCache).where(VideoCache.bvid == bvid)
    )
    video = result.scalar_one_or_none()
    if not video:
        raise HTTPException(status_code=404, detail="视频不存在")

    # 获取片段
    seg_result = await db.execute(
        select(Segment).where(Segment.video_bvid == bvid)
        .order_by(Segment.segment_index)
    )
    segments = seg_result.scalars().all()

    # 获取关联知识节点
    link_result = await db.execute(
        select(NodeSegmentLink).where(NodeSegmentLink.video_bvid == bvid)
    )
    links = link_result.scalars().all()

    node_ids = list(set(link.node_id for link in links))
    knowledge_nodes = []
    if node_ids:
        nodes_result = await db.execute(
            select(KnowledgeNode).where(KnowledgeNode.id.in_(node_ids))
        )
        for kn in nodes_result.scalars().all():
            # 找该节点在本视频中的时间范围
            node_segments = []
            for link in links:
                if link.node_id == kn.id:
                    for seg in segments:
                        if seg.id == link.segment_id:
                            node_segments.append({
                                "start_time": seg.start_time,
                                "end_time": seg.end_time,
                                "time_label": f"{_fmt_time(seg.start_time)}-{_fmt_time(seg.end_time)}" if seg.start_time is not None else "",
                            })

            # 树中位置
            gs = get_graph_store()
            if gs.node_count() == 0:
                await gs.load_from_db(db)
            builder = get_tree_builder()
            position = builder.get_node_tree_position(kn.id)

            knowledge_nodes.append({
                "id": kn.id,
                "name": kn.name,
                "node_type": kn.node_type,
                "difficulty": kn.difficulty,
                "definition": kn.definition,
                "confidence": kn.confidence,
                "segments": node_segments,
                "tree_position": position,
            })

    # 按时间排序知识点
    knowledge_nodes.sort(key=lambda n: (n["segments"][0]["start_time"] if n["segments"] else 9999))

    return {
        "bvid": video.bvid,
        "title": video.title,
        "description": video.description,
        "owner_name": video.owner_name,
        "duration": video.duration,
        "pic_url": video.pic_url,
        "summary": video.summary,
        "tags": video.tags or [],
        "url": f"https://www.bilibili.com/video/{video.bvid}",
        "knowledge_nodes": knowledge_nodes,
        "segments": [
            {
                "id": seg.id,
                "segment_index": seg.segment_index,
                "start_time": seg.start_time,
                "end_time": seg.end_time,
                "text": (seg.cleaned_text or seg.raw_text)[:300],
                "summary": seg.summary,
                "source_type": seg.source_type,
                "time_label": f"{_fmt_time(seg.start_time)}-{_fmt_time(seg.end_time)}" if seg.start_time is not None else "",
            }
            for seg in segments
        ],
    }


@router.get("/node/{node_id}/segments")
async def get_node_segments(node_id: int, db: AsyncSession = Depends(get_db)):
    """获取节点关联的所有片段"""
    links_result = await db.execute(
        select(NodeSegmentLink).where(NodeSegmentLink.node_id == node_id)
    )
    links = links_result.scalars().all()

    if not links:
        return []

    segment_ids = [link.segment_id for link in links]
    seg_result = await db.execute(
        select(Segment).where(Segment.id.in_(segment_ids))
        .order_by(Segment.start_time)
    )

    return [
        {
            "id": seg.id,
            "video_bvid": seg.video_bvid,
            "segment_index": seg.segment_index,
            "start_time": seg.start_time,
            "end_time": seg.end_time,
            "text": seg.cleaned_text or seg.raw_text,
            "summary": seg.summary,
            "source_type": seg.source_type,
            "time_label": f"{_fmt_time(seg.start_time)}-{_fmt_time(seg.end_time)}" if seg.start_time is not None else "",
            "url": f"https://www.bilibili.com/video/{seg.video_bvid}?t={int(seg.start_time)}" if seg.start_time is not None else None,
        }
        for seg in seg_result.scalars().all()
    ]


@router.get("/node/{node_id}/path")
async def get_learning_path(
    node_id: int,
    mode: str = Query("standard", description="beginner / standard / quick"),
    known: Optional[str] = Query(None, description="Comma-separated known node IDs"),
    db: AsyncSession = Depends(get_db),
):
    """生成学习路径推荐"""
    gs = get_graph_store()
    if gs.node_count() == 0:
        await gs.load_from_db(db)

    if not gs.has_node(node_id):
        raise HTTPException(status_code=404, detail="Node not found")

    if mode not in ("beginner", "standard", "quick"):
        mode = "standard"

    known_ids = []
    if known:
        try:
            known_ids = [int(x.strip()) for x in known.split(",") if x.strip()]
        except ValueError:
            pass

    recommender = get_path_recommender()
    result = recommender.recommend_path(node_id, mode=mode, known_node_ids=known_ids)

    # 为每个步骤填充视频信息
    for step in result.get("steps", []):
        nid = step["node_id"]
        vid_count = await db.scalar(
            select(func.count(func.distinct(NodeSegmentLink.video_bvid)))
            .where(NodeSegmentLink.node_id == nid)
        )
        step["has_videos"] = (vid_count or 0) > 0
        step["video_count"] = vid_count or 0

        # 获取代表性视频（最多2个）
        links = await db.execute(
            select(NodeSegmentLink.video_bvid)
            .where(NodeSegmentLink.node_id == nid)
            .distinct()
            .limit(2)
        )
        bvids = [row[0] for row in links.fetchall()]
        step["videos"] = []
        for bvid in bvids:
            vc = await db.execute(select(VideoCache).where(VideoCache.bvid == bvid))
            video = vc.scalar_one_or_none()
            if video:
                # 获取该节点在该视频中的片段
                seg_links = await db.execute(
                    select(NodeSegmentLink.segment_id)
                    .where(NodeSegmentLink.node_id == nid, NodeSegmentLink.video_bvid == bvid)
                )
                seg_ids = [r[0] for r in seg_links.fetchall()]
                segs = []
                if seg_ids:
                    seg_result = await db.execute(
                        select(Segment).where(Segment.id.in_(seg_ids)).order_by(Segment.start_time)
                    )
                    for seg in seg_result.scalars().all():
                        segs.append({
                            "time_label": f"{_fmt_time(seg.start_time)}-{_fmt_time(seg.end_time)}" if seg.start_time is not None else "",
                            "url": f"https://www.bilibili.com/video/{bvid}?t={int(seg.start_time)}" if seg.start_time is not None else None,
                        })

                step["videos"].append({
                    "bvid": video.bvid,
                    "title": video.title,
                    "url": f"https://www.bilibili.com/video/{video.bvid}",
                    "segments": segs,
                })

    return result


@router.get("/stats")
async def get_tree_stats(db: AsyncSession = Depends(get_db)):
    """获取知识树统计"""
    node_count = await db.scalar(select(func.count()).select_from(KnowledgeNode))
    edge_count = await db.scalar(select(func.count()).select_from(KnowledgeEdge))
    segment_count = await db.scalar(select(func.count()).select_from(Segment))
    topic_count = await db.scalar(
        select(func.count()).select_from(KnowledgeNode)
        .where(KnowledgeNode.node_type == "topic")
    )
    pending_count = await db.scalar(
        select(func.count()).select_from(KnowledgeNode)
        .where(KnowledgeNode.review_status == "pending_review")
    )
    video_count = await db.scalar(
        select(func.count(func.distinct(Segment.video_bvid))).select_from(Segment)
    )

    return {
        "total_nodes": node_count or 0,
        "total_edges": edge_count or 0,
        "total_segments": segment_count or 0,
        "total_topics": topic_count or 0,
        "total_videos": video_count or 0,
        "pending_review": pending_count or 0,
    }


@router.get("/pending")
async def get_pending_nodes(
    limit: int = Query(50, le=200),
    db: AsyncSession = Depends(get_db),
):
    """获取待审核节点列表"""
    result = await db.execute(
        select(KnowledgeNode)
        .where(KnowledgeNode.review_status == "pending_review")
        .order_by(KnowledgeNode.source_count.desc())
        .limit(limit)
    )
    nodes = result.scalars().all()
    return [
        {
            "id": n.id,
            "name": n.name,
            "node_type": n.node_type,
            "definition": n.definition,
            "confidence": n.confidence,
            "source_count": n.source_count,
        }
        for n in nodes
    ]


@router.post("/node/{node_id}/review")
async def review_node(
    node_id: int,
    action: str = Query(..., description="approve 或 reject"),
    db: AsyncSession = Depends(get_db),
):
    """审核知识节点"""
    if action not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="action 必须为 approve 或 reject")

    result = await db.execute(
        select(KnowledgeNode).where(KnowledgeNode.id == node_id)
    )
    node = result.scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=404, detail="节点不存在")

    node.review_status = "approved" if action == "approve" else "rejected"
    await db.commit()

    # 同步图
    gs = get_graph_store()
    if gs.has_node(node_id):
        gs.graph.nodes[node_id]["review_status"] = node.review_status

    return {"message": f"节点 {node.name} 已{action}", "review_status": node.review_status}


# ==================== 辅助函数 ====================

async def _fill_video_counts(tree_nodes: list[dict], db: AsyncSession) -> None:
    """递归填充树节点的 video_count"""
    for node in tree_nodes:
        node_id = node.get("id")
        if node_id and node_id > 0:
            count = await db.scalar(
                select(func.count(func.distinct(NodeSegmentLink.video_bvid)))
                .where(NodeSegmentLink.node_id == node_id)
            )
            node["video_count"] = count or 0

        if node.get("children"):
            await _fill_video_counts(node["children"], db)


def _filter_tree_by_difficulty(tree: list[dict], diff_range: tuple[int, int]) -> list[dict]:
    """按难度范围过滤知识树节点（保留主题节点作为父级）"""
    lo, hi = diff_range
    filtered = []
    for topic in tree:
        # 主题节点始终保留，但过滤其子节点
        children = _filter_children_by_difficulty(topic.get("children", []), lo, hi)
        if children or topic.get("node_type") == "topic":
            new_topic = dict(topic)
            new_topic["children"] = children
            new_topic["node_count"] = len(children)
            filtered.append(new_topic)
    return filtered


def _filter_children_by_difficulty(children: list[dict], lo: int, hi: int) -> list[dict]:
    """递归过滤子节点"""
    result = []
    for child in children:
        diff = child.get("difficulty", 1)
        sub_children = _filter_children_by_difficulty(child.get("children", []), lo, hi)
        if lo <= diff <= hi or sub_children:
            new_child = dict(child)
            new_child["children"] = sub_children
            new_child["node_count"] = len(sub_children)
            result.append(new_child)
    return result
