"""
BiliMind 知识树学习导航系统

知识树路由 — 树结构、节点详情、视频详情
"""
import re
from typing import Optional
from fastapi import APIRouter, HTTPException, Query, Depends
from loguru import logger
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import KnowledgeNode, KnowledgeEdge, NodeSegmentLink, Segment, VideoCache, _fmt_time
from app.services.graph_store import GraphStore
from app.services.tree_builder import TreeBuilder, _is_noise_name, _compute_grade
from app.services.path_recommender import PathRecommender
from app.services.evidence_ranker import get_evidence_ranker, build_reason, rule_score_segment_match, confidence_level_from_score
from app.config import settings

router = APIRouter(prefix="/tree", tags=["知识树"])

async def _load_graph_store(db: AsyncSession, session_id: Optional[str] = None) -> GraphStore:
    """为当前请求加载隔离后的图谱快照。"""
    gs = GraphStore(graph_path=settings.graph_persist_path)
    await gs.load_from_db(db, session_id=session_id)
    return gs


def _make_tree_builder(gs: GraphStore) -> TreeBuilder:
    return TreeBuilder(gs)


def _make_path_recommender(gs: GraphStore) -> PathRecommender:
    return PathRecommender(gs)


def _score_segment_match(
    node: KnowledgeNode,
    link: NodeSegmentLink,
    segment: Segment,
    video: Optional[VideoCache] = None,
) -> float:
    return rule_score_segment_match(node, link, segment, video)


@router.get("")
async def get_knowledge_tree(
    min_confidence: Optional[float] = Query(None, description="最低置信度"),
    topic_id: Optional[int] = Query(None, description="按主题筛选（只返回该主题子树）"),
    stage: Optional[str] = Query(None, description="按难度阶段筛选: beginner/intermediate/advanced"),
    session_id: Optional[str] = Query(None, description="会话ID，用于数据隔离"),
    db: AsyncSession = Depends(get_db),
):
    """获取完整知识树结构（支持主题筛选和阶段筛选）"""
    try:
        gs = await _load_graph_store(db, session_id=session_id)
        builder = _make_tree_builder(gs)
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
        await _fill_video_counts(tree_data["tree"], db, session_id=session_id)

        return tree_data
    except Exception as e:
        logger.error(f"获取知识树失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/graph")
async def get_knowledge_graph(
    topic_id: Optional[int] = Query(None, description="按主题筛选子图"),
    min_confidence: Optional[float] = Query(None, description="最低置信度"),
    session_id: Optional[str] = Query(None, description="会话ID，用于数据隔离"),
    db: AsyncSession = Depends(get_db),
):
    """获取完整知识图谱数据（适配 3D force-graph 可视化）"""
    try:
        gs = await _load_graph_store(db, session_id=session_id)

        threshold = min_confidence or settings.tree_min_confidence

        # 社区信息当前不跨用户缓存，避免串号
        community_map: dict[int, int] = {}

        # 收集并过滤节点
        all_nodes = gs.all_nodes()
        nodes = []
        valid_ids = set()

        for n in all_nodes:
            if n.get("review_status") == "rejected":
                continue
            if n.get("confidence", 0) < threshold:
                continue
            if _is_noise_name(n.get("name", "")):
                continue
            valid_ids.add(n["id"])
            grade = _compute_grade(n)
            node_data = {
                "id": n["id"],
                "name": n.get("name", ""),
                "node_type": n.get("node_type", "concept"),
                "difficulty": n.get("difficulty", 1),
                "confidence": round(n.get("confidence", 0.5), 2),
                "source_count": n.get("source_count", 1),
                "definition": n.get("definition", ""),
                "grade": grade,
                "val": max(1, n.get("source_count", 1)),
            }
            if n["id"] in community_map:
                node_data["community_id"] = community_map[n["id"]]
            nodes.append(node_data)

        # 如果指定了 topic_id，只保留该主题的子图节点
        if topic_id is not None:
            subgraph_ids = set()
            _collect_subtree_ids(gs, topic_id, subgraph_ids, valid_ids)
            subgraph_ids.add(topic_id)
            nodes = [n for n in nodes if n["id"] in subgraph_ids]
            valid_ids = subgraph_ids & valid_ids

        # 收集边（只保留两端都在 valid_ids 中的边）
        links = []
        if gs.graph is not None:
            for src, tgt, data in gs.graph.edges(data=True):
                if src in valid_ids and tgt in valid_ids:
                    links.append({
                        "source": src,
                        "target": tgt,
                        "relation_type": data.get("relation_type", "related_to"),
                        "weight": round(data.get("weight", 1.0), 2),
                        "confidence": round(data.get("confidence", 0.5), 2),
                    })

        return {
            "nodes": nodes,
            "links": links,
            "stats": {
                "node_count": len(nodes),
                "link_count": len(links),
            }
        }
    except Exception as e:
        logger.error(f"获取知识图谱失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def _collect_subtree_ids(gs: GraphStore, parent_id: int, collected: set, valid_ids: set, depth: int = 0):
    """递归收集子树中的所有节点 ID"""
    if depth > 10:
        return
    children = gs.get_children(parent_id)
    for child in children:
        cid = child["id"]
        if cid in valid_ids and cid not in collected:
            collected.add(cid)
            _collect_subtree_ids(gs, cid, collected, valid_ids, depth + 1)


@router.get("/topics")
async def get_topics(
    session_id: Optional[str] = Query(None, description="会话ID，用于数据隔离"),
    db: AsyncSession = Depends(get_db),
):
    """获取一级主题列表"""
    try:
        query = select(KnowledgeNode).where(KnowledgeNode.node_type == "topic")
        if session_id:
            query = query.where(KnowledgeNode.session_id == session_id)
        result = await db.execute(
            query.order_by(KnowledgeNode.source_count.desc())
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
async def get_node_detail(
    node_id: int,
    session_id: Optional[str] = Query(None, description="会话ID，用于数据隔离"),
    db: AsyncSession = Depends(get_db),
):
    """获取知识节点详情"""
    node_query = select(KnowledgeNode).where(KnowledgeNode.id == node_id)
    if session_id:
        node_query = node_query.where(KnowledgeNode.session_id == session_id)
    result = await db.execute(node_query)
    node = result.scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=404, detail="节点不存在")

    gs = await _load_graph_store(db, session_id=session_id)

    # 主归属
    main_topic = None
    if node.main_topic_id:
        topic_query = select(KnowledgeNode).where(KnowledgeNode.id == node.main_topic_id)
        if session_id:
            topic_query = topic_query.where(KnowledgeNode.session_id == session_id)
        topic_result = await db.execute(topic_query)
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
    links_query = select(NodeSegmentLink).where(NodeSegmentLink.node_id == node_id)
    if session_id:
        links_query = links_query.where(NodeSegmentLink.session_id == session_id)
    links_result = await db.execute(links_query)
    links = links_result.scalars().all()

    segment_ids = [link.segment_id for link in links if link.segment_id]
    segment_map: dict[int, Segment] = {}
    if segment_ids:
        segment_query = select(Segment).where(Segment.id.in_(segment_ids))
        if session_id:
            segment_query = segment_query.where(Segment.session_id == session_id)
        seg_rows = await db.execute(segment_query)
        segment_map = {seg.id: seg for seg in seg_rows.scalars().all()}

    video_map: dict[str, VideoCache] = {}
    if segment_map:
        related_bvids = list({seg.video_bvid for seg in segment_map.values() if seg.video_bvid})
        if related_bvids:
            video_rows = await db.execute(select(VideoCache).where(VideoCache.bvid.in_(related_bvids)))
            video_map = {item.bvid: item for item in video_rows.scalars().all()}

    # 收集并排序视频证据
    ranker = get_evidence_ranker()
    scored_links: list[tuple[NodeSegmentLink, Segment, float, float]] = []
    for link in links:
        seg = segment_map.get(link.segment_id)
        if not seg:
            continue
        bvid = link.video_bvid or seg.video_bvid
        video = video_map.get(bvid) if bvid else None
        score_payload = ranker.score(node, link, seg, video)
        score = float(score_payload["score"])
        model_score = float(score_payload["model_score"])
        if not bool(score_payload["is_relevant"]):
            continue
        scored_links.append((link, seg, score, model_score))

    scored_links.sort(
        key=lambda item: (
            -item[2],
            -item[3],
            item[1].start_time if item[1].start_time is not None else 10**9,
            item[1].segment_index,
        )
    )

    video_scores: dict[str, dict] = {}
    support_count = len({seg.video_bvid for _, seg, _, _ in scored_links if seg.video_bvid})
    for link, seg, score, model_score in scored_links:
        bvid = link.video_bvid or seg.video_bvid
        if not bvid:
            continue
        entry = video_scores.setdefault(bvid, {"score": score, "segments": []})
        entry["score"] = max(entry["score"], score)
        if len(entry["segments"]) >= 3:
            continue
        entry["segments"].append({
            "id": seg.id,
            "start_time": seg.start_time,
            "end_time": seg.end_time,
            "text": (seg.cleaned_text or seg.raw_text)[:240],
            "time_label": f"{_fmt_time(seg.start_time)}-{_fmt_time(seg.end_time)}" if seg.start_time is not None else "",
            "match_confidence": round(score, 3),
            "confidence_level": confidence_level_from_score(score),
            "match_reason": build_reason(
                node,
                seg.cleaned_text or seg.raw_text,
                semantic_boost=model_score,
                support_count=support_count,
                video_title=video_map.get(bvid).title if video_map.get(bvid) else "",
            ),
        })

    video_bvids = list(video_scores.keys())
    videos = []
    if video_bvids:
        vids_result = await db.execute(
            select(VideoCache).where(VideoCache.bvid.in_(video_bvids))
        )
        for vc in vids_result.scalars().all():
            videos.append({
                "bvid": vc.bvid,
                "title": vc.title,
                "owner_name": vc.owner_name,
                "pic_url": vc.pic_url,
                "duration": vc.duration,
                "evidence_score": round(video_scores[vc.bvid]["score"], 3),
                "segments": video_scores[vc.bvid]["segments"],
                "url": f"https://www.bilibili.com/video/{vc.bvid}",
            })
    videos.sort(key=lambda v: (-v["evidence_score"], v["title"]))

    # 树中位置
    builder = _make_tree_builder(gs)
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
async def get_video_detail(
    bvid: str,
    session_id: Optional[str] = Query(None, description="会话ID，用于数据隔离"),
    db: AsyncSession = Depends(get_db),
):
    """获取视频详情（知识点 + 时间片段 + 树中位置）"""
    result = await db.execute(select(VideoCache).where(VideoCache.bvid == bvid))
    video = result.scalar_one_or_none()
    if not video:
        raise HTTPException(status_code=404, detail="视频不存在")

    # 获取片段
    seg_query = select(Segment).where(Segment.video_bvid == bvid)
    if session_id:
        seg_query = seg_query.where(Segment.session_id == session_id)
    seg_result = await db.execute(seg_query.order_by(Segment.segment_index))
    segments = seg_result.scalars().all()

    # 获取关联知识节点
    link_query = select(NodeSegmentLink).where(NodeSegmentLink.video_bvid == bvid)
    if session_id:
        link_query = link_query.where(NodeSegmentLink.session_id == session_id)
    link_result = await db.execute(link_query)
    links = link_result.scalars().all()

    if session_id and not segments and not links:
        raise HTTPException(status_code=404, detail="当前用户下视频不存在")

    node_ids = list(set(link.node_id for link in links))
    knowledge_nodes = []
    if node_ids:
        nodes_query = select(KnowledgeNode).where(KnowledgeNode.id.in_(node_ids))
        if session_id:
            nodes_query = nodes_query.where(KnowledgeNode.session_id == session_id)
        nodes_result = await db.execute(nodes_query)
        gs = await _load_graph_store(db, session_id=session_id)
        builder = _make_tree_builder(gs)
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
async def get_node_segments(
    node_id: int,
    session_id: Optional[str] = Query(None, description="会话ID，用于数据隔离"),
    db: AsyncSession = Depends(get_db),
):
    """获取节点关联的所有片段"""
    links_query = select(NodeSegmentLink).where(NodeSegmentLink.node_id == node_id)
    if session_id:
        links_query = links_query.where(NodeSegmentLink.session_id == session_id)
    links_result = await db.execute(links_query)
    links = links_result.scalars().all()

    if not links:
        return []

    segment_ids = [link.segment_id for link in links]
    seg_query = select(Segment).where(Segment.id.in_(segment_ids))
    if session_id:
        seg_query = seg_query.where(Segment.session_id == session_id)
    seg_result = await db.execute(seg_query.order_by(Segment.start_time))

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
    session_id: Optional[str] = Query(None, description="会话ID，用于数据隔离"),
    db: AsyncSession = Depends(get_db),
):
    """生成学习路径推荐"""
    gs = await _load_graph_store(db, session_id=session_id)

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

    recommender = _make_path_recommender(gs)
    result = recommender.recommend_path(node_id, mode=mode, known_node_ids=known_ids)

    # 为每个步骤填充视频信息
    for step in result.get("steps", []):
        nid = step["node_id"]
        vid_count_query = select(func.count(func.distinct(NodeSegmentLink.video_bvid))).where(
            NodeSegmentLink.node_id == nid
        )
        if session_id:
            vid_count_query = vid_count_query.where(NodeSegmentLink.session_id == session_id)
        vid_count = await db.scalar(vid_count_query)
        step["has_videos"] = (vid_count or 0) > 0
        step["video_count"] = vid_count or 0

        # 获取代表性视频（最多2个）
        links_query = select(NodeSegmentLink.video_bvid).where(NodeSegmentLink.node_id == nid)
        if session_id:
            links_query = links_query.where(NodeSegmentLink.session_id == session_id)
        links = await db.execute(links_query.distinct().limit(2))
        bvids = [row[0] for row in links.fetchall()]
        step["videos"] = []
        for bvid in bvids:
            vc = await db.execute(select(VideoCache).where(VideoCache.bvid == bvid))
            video = vc.scalar_one_or_none()
            if video:
                # 获取该节点在该视频中的片段
                seg_links_query = select(NodeSegmentLink.segment_id).where(
                    NodeSegmentLink.node_id == nid,
                    NodeSegmentLink.video_bvid == bvid,
                )
                if session_id:
                    seg_links_query = seg_links_query.where(NodeSegmentLink.session_id == session_id)
                seg_links = await db.execute(seg_links_query)
                seg_ids = [r[0] for r in seg_links.fetchall()]
                segs = []
                if seg_ids:
                    seg_query = select(Segment).where(Segment.id.in_(seg_ids))
                    if session_id:
                        seg_query = seg_query.where(Segment.session_id == session_id)
                    seg_result = await db.execute(seg_query.order_by(Segment.start_time))
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
        segment_count = sum(len(video.get("segments", [])) for video in step["videos"])
        evidence_score = min(1.0, (min(3, step["video_count"]) / 3.0) * 0.65 + (min(4, segment_count) / 4.0) * 0.35)
        priority_score = float(step.get("priority_score", 0.0) or 0.0)
        step["segment_count"] = segment_count
        step["evidence_score"] = round(evidence_score, 3)
        step["composite_score"] = round(priority_score * 0.7 + evidence_score * 0.3, 3)
        if evidence_score >= 0.75:
            step["support_label"] = "strong"
        elif evidence_score >= 0.45:
            step["support_label"] = "medium"
        else:
            step["support_label"] = "weak"

    if result.get("steps"):
        summary = result.get("summary") or {}
        steps = result["steps"]
        summary.update({
            "avg_evidence_score": round(sum(float(step.get("evidence_score", 0.0) or 0.0) for step in steps) / len(steps), 3),
            "avg_composite_score": round(sum(float(step.get("composite_score", 0.0) or 0.0) for step in steps) / len(steps), 3),
            "strong_support_steps": sum(1 for step in steps if step.get("support_label") == "strong"),
        })
        result["summary"] = summary

    return result


@router.get("/stats")
async def get_tree_stats(
    session_id: Optional[str] = Query(None, description="会话ID，用于数据隔离"),
    db: AsyncSession = Depends(get_db),
):
    """获取知识树统计"""
    if session_id:
        node_count = await db.scalar(select(func.count()).select_from(KnowledgeNode).where(KnowledgeNode.session_id == session_id))
        edge_count = await db.scalar(select(func.count()).select_from(KnowledgeEdge).where(KnowledgeEdge.session_id == session_id))
        segment_count = await db.scalar(select(func.count()).select_from(Segment).where(Segment.session_id == session_id))
        topic_count = await db.scalar(
            select(func.count()).select_from(KnowledgeNode)
            .where(KnowledgeNode.node_type == "topic", KnowledgeNode.session_id == session_id)
        )
        pending_count = await db.scalar(
            select(func.count()).select_from(KnowledgeNode)
            .where(KnowledgeNode.review_status == "pending_review", KnowledgeNode.session_id == session_id)
        )
        video_count = await db.scalar(
            select(func.count(func.distinct(Segment.video_bvid))).select_from(Segment).where(Segment.session_id == session_id)
        )
    else:
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
    session_id: Optional[str] = Query(None, description="会话ID，用于数据隔离"),
    db: AsyncSession = Depends(get_db),
):
    """获取待审核节点列表"""
    query = select(KnowledgeNode).where(KnowledgeNode.review_status == "pending_review")
    if session_id:
        query = query.where(KnowledgeNode.session_id == session_id)
    result = await db.execute(
        query.order_by(KnowledgeNode.source_count.desc()).limit(limit)
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
    session_id: Optional[str] = Query(None, description="会话ID，用于数据隔离"),
    db: AsyncSession = Depends(get_db),
):
    """审核知识节点"""
    if action not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="action 必须为 approve 或 reject")

    query = select(KnowledgeNode).where(KnowledgeNode.id == node_id)
    if session_id:
        query = query.where(KnowledgeNode.session_id == session_id)
    result = await db.execute(query)
    node = result.scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=404, detail="节点不存在")

    node.review_status = "approved" if action == "approve" else "rejected"
    await db.commit()

    return {"message": f"节点 {node.name} 已{action}", "review_status": node.review_status}


# ==================== 辅助函数 ====================

async def _fill_video_counts(tree_nodes: list[dict], db: AsyncSession, session_id: Optional[str] = None) -> None:
    """递归填充树节点的 video_count"""
    for node in tree_nodes:
        node_id = node.get("id")
        if node_id and node_id > 0:
            count_query = select(func.count(func.distinct(NodeSegmentLink.video_bvid))).where(
                NodeSegmentLink.node_id == node_id
            )
            if session_id:
                count_query = count_query.where(NodeSegmentLink.session_id == session_id)
            count = await db.scalar(count_query)
            node["video_count"] = count or 0

        if node.get("children"):
            await _fill_video_counts(node["children"], db, session_id=session_id)


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
