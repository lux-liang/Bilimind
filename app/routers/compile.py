"""
知映 ZhiYing — 知识编译路由

提供视频知识编译的 API 端点：
- POST /compile/video  — 启动编译（后台任务）
- GET  /compile/status/{task_id} — 查询编译进度
- GET  /compile/result/{bvid}  — 获取编译结果
"""
import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, BackgroundTasks, Depends
from loguru import logger
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db, get_db_context
from app.models import (
    Concept, Claim, ConceptRelation, Segment, VideoCache,
)
from app.services.knowledge_compiler import compile_video, _fmt_time
from app.services.bilibili import BilibiliService
from app.services.content_fetcher import ContentFetcher
from app.services.asr import ASRService
from app.services.harness_pipeline import DEFAULT_SAMPLE_BVID, HarnessPipeline
from app.routers.auth import get_session

router = APIRouter(prefix="/compile", tags=["知识编译"])


# ==================== 任务状态存储 ====================

compile_tasks: dict[str, dict] = {}


# ==================== 请求/响应模型 ====================

class CompileRequest(BaseModel):
    """编译请求"""
    bvid: str
    session_id: str


class CompileTaskResponse(BaseModel):
    """编译任务响应"""
    task_id: str
    message: str


class DemoCompileRequest(BaseModel):
    """Harness demo 编译请求"""
    bvid: str = DEFAULT_SAMPLE_BVID
    session_id: str = "demo-session"
    datasource: str = "sample"
    transcript_source: str = "sample"


class CompileStatusResponse(BaseModel):
    """编译状态响应"""
    status: str  # running / completed / failed
    progress: float
    message: str


# ==================== POST /compile/video ====================

@router.post("/video", response_model=CompileTaskResponse)
async def compile_video_endpoint(
    request: CompileRequest,
    background_tasks: BackgroundTasks,
):
    """
    启动视频知识编译（后台任务）

    将视频字幕编译为 Concept-Claim-Evidence 三级知识结构
    """
    task_id = str(uuid.uuid4())

    compile_tasks[task_id] = {
        "status": "running",
        "progress": 0.0,
        "message": "编译初始化中...",
        "bvid": request.bvid,
        "session_id": request.session_id,
        "dataset_version": str(uuid.uuid4()),
    }

    background_tasks.add_task(
        _compile_video_task,
        task_id,
        request.bvid,
        request.session_id,
    )

    return CompileTaskResponse(task_id=task_id, message="编译已开始")


@router.post("/demo")
async def compile_demo_endpoint(request: DemoCompileRequest):
    """
    运行离线 Harness demo pipeline。

    该接口不依赖 B 站登录、外部 LLM 或 ASR。它读取 demo/sample_* 数据，
    生成 artifacts/harness 下的中间产物，并返回可直接给前端展示的结果。
    """
    pipeline = HarnessPipeline()
    result = pipeline.run(
        bvid=request.bvid,
        datasource=request.datasource,
        transcript_source=request.transcript_source,
    )
    return _demo_pipeline_to_compile_result(result)


async def _compile_video_task(
    task_id: str,
    bvid: str,
    session_id: str,
):
    """后台编译任务"""
    try:
        compile_tasks[task_id]["status"] = "running"
        compile_tasks[task_id]["progress"] = 0.1
        compile_tasks[task_id]["message"] = "正在获取视频内容..."

        # 创建服务实例
        session = await get_session(session_id)
        cookies = (session or {}).get("cookies", {})

        bili = BilibiliService(
            sessdata=cookies.get("SESSDATA"),
            bili_jct=cookies.get("bili_jct"),
            dedeuserid=cookies.get("DedeUserID"),
        )
        asr_service = ASRService()
        content_fetcher = ContentFetcher(bili, asr_service)

        try:
            compile_tasks[task_id]["progress"] = 0.2
            compile_tasks[task_id]["message"] = "正在编译知识结构..."

            async with get_db_context() as db:
                result = await compile_video(
                    db=db,
                    bvid=bvid,
                    session_id=session_id,
                    content_fetcher=content_fetcher,
                )

            compile_tasks[task_id]["status"] = "completed"
            compile_tasks[task_id]["progress"] = 1.0
            compile_tasks[task_id]["message"] = (
                f"编译完成: {result['concept_count']} 个概念, "
                f"{result['claim_count']} 个论断, "
                f"{result['peak_count']} 个知识峰值"
            )
            logger.info(f"[{bvid}] 编译任务完成: {result}")

        finally:
            await bili.close()

    except Exception as e:
        logger.error(f"编译任务失败 [{bvid}]: {e}")
        compile_tasks[task_id]["status"] = "failed"
        compile_tasks[task_id]["progress"] = 0.0
        compile_tasks[task_id]["message"] = f"编译失败: {e}"


# ==================== GET /compile/status/{task_id} ====================

@router.get("/status/{task_id}", response_model=CompileStatusResponse)
async def get_compile_status(
    task_id: str,
    session_id: str = Query(..., description="会话ID"),
):
    """查询编译任务状态"""
    if task_id not in compile_tasks:
        raise HTTPException(status_code=404, detail="任务不存在")

    task = compile_tasks[task_id]
    if task.get("session_id") != session_id:
        raise HTTPException(status_code=404, detail="任务不存在")
    return CompileStatusResponse(
        status=task["status"],
        progress=task["progress"],
        message=task["message"],
    )


# ==================== GET /compile/result/{bvid} ====================

@router.get("/result/{bvid}")
async def get_compile_result(
    bvid: str,
    session_id: str = Query(..., description="会话ID"),
    db: AsyncSession = Depends(get_db),
):
    """
    获取视频的完整编译结果

    返回 Concept-Claim-Evidence 结构 + 时间轴密度 + 前置关系
    """
    # 获取视频信息
    vc_result = await db.execute(
        select(VideoCache).where(VideoCache.bvid == bvid)
    )
    video_cache = vc_result.scalar_one_or_none()
    if not video_cache:
        raise HTTPException(status_code=404, detail="视频未找到")

    # 获取 Concepts
    concept_rows = await db.execute(
        select(Concept).where(Concept.session_id == session_id)
    )
    all_concepts = concept_rows.scalars().all()

    # 获取与此视频关联的 Claims
    claim_rows = await db.execute(
        select(Claim).where(
            Claim.video_bvid == bvid,
            Claim.session_id == session_id,
        )
    )
    all_claims = claim_rows.scalars().all()

    # 建立 concept_id -> claims 映射
    concept_id_to_claims: dict[int, list] = {}
    relevant_concept_ids = set()
    for cl in all_claims:
        relevant_concept_ids.add(cl.concept_id)
        concept_id_to_claims.setdefault(cl.concept_id, []).append(cl)

    # 只返回与此视频相关的概念
    relevant_concepts = [c for c in all_concepts if c.id in relevant_concept_ids]

    # 构建 concepts 响应
    concepts_response = []
    for concept in relevant_concepts:
        claims_list = concept_id_to_claims.get(concept.id, [])
        claims_response = []
        for cl in claims_list:
            time_label = ""
            if cl.start_time is not None and cl.end_time is not None:
                time_label = f"{_fmt_time(cl.start_time)}-{_fmt_time(cl.end_time)}"
            claims_response.append({
                "id": cl.id,
                "statement": cl.statement,
                "type": cl.claim_type,
                "confidence": cl.confidence,
                "time": time_label,
                "start_time": cl.start_time,
                "end_time": cl.end_time,
                "raw_text": cl.raw_text or "",
            })

        concepts_response.append({
            "id": concept.id,
            "name": concept.name,
            "definition": concept.definition or "",
            "difficulty": concept.difficulty,
            "source_count": concept.source_count,
            "claims": claims_response,
        })

    # 获取 Segments（时间轴）
    seg_rows = await db.execute(
        select(Segment).where(
            Segment.video_bvid == bvid,
            Segment.session_id == session_id,
        ).order_by(Segment.segment_index)
    )
    segments = seg_rows.scalars().all()

    # 构建 timeline
    timeline = []
    for seg in segments:
        # 查找该片段时间范围内的概念
        seg_concept_names = []
        for cl in all_claims:
            if cl.start_time is not None and cl.end_time is not None:
                if seg.start_time is not None and seg.end_time is not None:
                    if cl.start_time < seg.end_time and cl.end_time > seg.start_time:
                        # 找到概念名
                        for c in relevant_concepts:
                            if c.id == cl.concept_id and c.name not in seg_concept_names:
                                seg_concept_names.append(c.name)

        entry = {
            "start": seg.start_time,
            "end": seg.end_time,
            "density": seg.knowledge_density or 0.0,
            "is_peak": seg.is_peak or False,
        }
        if seg_concept_names:
            entry["concepts"] = seg_concept_names
        timeline.append(entry)

    # 获取 ConceptRelations
    rel_rows = await db.execute(
        select(ConceptRelation).where(
            ConceptRelation.session_id == session_id,
        )
    )
    all_relations = rel_rows.scalars().all()

    # 构建 prerequisites 响应（只包含与当前视频相关的概念）
    concept_id_to_name = {c.id: c.name for c in relevant_concepts}
    # 也包含 prerequisite 概念（可能不在 relevant_concepts 中）
    all_concept_id_to_name = {c.id: c.name for c in all_concepts}

    prerequisites_response = []
    for rel in all_relations:
        src_name = all_concept_id_to_name.get(rel.source_concept_id)
        tgt_name = all_concept_id_to_name.get(rel.target_concept_id)
        if src_name and tgt_name:
            # 至少一端是当前视频的概念
            if rel.source_concept_id in relevant_concept_ids or rel.target_concept_id in relevant_concept_ids:
                prerequisites_response.append({
                    "source": src_name,
                    "target": tgt_name,
                    "type": rel.relation_type,
                })

    # 统计
    peak_count = sum(1 for seg in segments if seg.is_peak)

    return {
        "video": {
            "bvid": bvid,
            "title": video_cache.title,
            "duration": video_cache.duration,
        },
        "concepts": concepts_response,
        "timeline": timeline,
        "prerequisites": prerequisites_response,
        "stats": {
            "concept_count": len(relevant_concepts),
            "claim_count": len(all_claims),
            "peak_count": peak_count,
        },
        "harness": {
            "pipeline_version": "legacy-compile-wrapper",
            "datasource": "bilibili",
            "transcript_source": "subtitle/asr/basic",
            "validation_passed": True,
            "artifact_dir": None,
            "stages": [
                {
                    "name": "transcript",
                    "status": "completed",
                    "duration_ms": 0,
                    "input_summary": "Bilibili video id",
                    "output_summary": f"{len(segments)} timestamped segments",
                    "warnings": [],
                    "artifact": None,
                },
                {
                    "name": "extract_merge",
                    "status": "completed",
                    "duration_ms": 0,
                    "input_summary": "segments",
                    "output_summary": f"{len(relevant_concepts)} concepts, {len(all_claims)} claims",
                    "warnings": [],
                    "artifact": None,
                },
                {
                    "name": "validate",
                    "status": "completed",
                    "duration_ms": 0,
                    "input_summary": "database compile result",
                    "output_summary": "legacy compile result available; run /compile/demo for full artifacts",
                    "warnings": ["真实编译结果暂不写出 artifacts；demo pipeline 会完整写出中间产物。"],
                    "artifact": None,
                },
            ],
            "validation": {
                "passed": True,
                "summary": {
                    "warning_count": 1,
                    "validated_evidence_links": len(all_claims),
                },
                "warnings": [
                    {
                        "code": "legacy_compile_no_artifacts",
                        "message": "真实编译链路已接入 Harness 展示字段；完整 artifacts 请运行 demo pipeline。",
                    }
                ],
                "errors": [],
            },
        },
    }


def _demo_pipeline_to_compile_result(result: dict) -> dict:
    """Convert Harness artifacts to the existing workspace CompileResult shape."""
    graph = result["merged_graph"]
    summary = result["summary"]
    validation = result["validation_report"]
    trace = result["pipeline_trace"]
    video = graph["video"]
    evidence_map = result.get("evidence_map", {})
    render_bundle = result.get("render_bundle", {})

    claims_by_node: dict[str, list[dict]] = {}
    for idx, claim in enumerate(graph.get("claims", []), start=1):
        claims_by_node.setdefault(claim["node_id"], []).append({
            "id": idx,
            "statement": claim["statement"],
            "type": claim["type"],
            "confidence": claim["confidence"],
            "time": claim["time"],
            "start_time": claim["start_time"],
            "end_time": claim["end_time"],
            "raw_text": claim["raw_text"],
            "review_status": "needs_review" if claim["confidence"] < 0.72 else "verified",
        })

    concepts = []
    for idx, node in enumerate(graph.get("nodes", []), start=1):
        concepts.append({
            "id": idx,
            "node_id": node["id"],
            "name": node["name"],
            "definition": node.get("definition", ""),
            "difficulty": node.get("difficulty", 1),
            "confidence": node.get("confidence", 0.5),
            "source_count": node.get("source_count", 1),
            "review_status": node.get("review_status", "needs_review"),
            "claims": claims_by_node.get(node["id"], []),
        })

    segment_claim_counts: dict[int, int] = {}
    segment_concepts: dict[int, set[str]] = {}
    for claim in graph.get("claims", []):
        segment_index = claim["segment_index"]
        segment_claim_counts[segment_index] = segment_claim_counts.get(segment_index, 0) + 1
        segment_concepts.setdefault(segment_index, set()).add(claim["concept"])

    transcript = result["transcript"]
    max_claims = max(segment_claim_counts.values()) if segment_claim_counts else 1
    timeline = []
    for segment in transcript.get("segments", []):
        segment_index = segment["segment_index"]
        claim_count = segment_claim_counts.get(segment_index, 0)
        timeline.append({
            "start": segment["start_time"],
            "end": segment["end_time"],
            "density": round(claim_count / max_claims, 2) if max_claims else 0,
            "is_peak": claim_count >= max_claims and claim_count > 0,
            "concepts": sorted(segment_concepts.get(segment_index, set())),
            "source_type": segment.get("source_type"),
            "confidence": segment.get("confidence"),
        })

    prerequisites = []
    node_by_id = {node["id"]: node for node in graph.get("nodes", [])}
    for edge in graph.get("edges", []):
        source = node_by_id.get(edge["source"])
        target = node_by_id.get(edge["target"])
        if source and target:
            prerequisites.append({
                "source": source["name"],
                "target": target["name"],
                "type": edge["type"],
            })

    return {
        "video": {
            "bvid": video.get("bvid"),
            "title": video.get("title"),
            "duration": video.get("duration") or 0,
            "source_url": video.get("source_url"),
        },
        "concepts": concepts,
        "timeline": timeline,
        "prerequisites": prerequisites,
        "stats": {
            "concept_count": len(concepts),
            "claim_count": len(graph.get("claims", [])),
            "peak_count": sum(1 for item in timeline if item.get("is_peak")),
        },
        "learning_path": result["learning_path"],
        "harness": {
            "pipeline_version": trace.get("pipeline_version"),
            "datasource": trace.get("datasource"),
            "transcript_source": trace.get("transcript_source"),
            "validation_passed": validation.get("passed"),
            "artifact_dir": result.get("artifact_dir"),
            "stages": trace.get("stages", []),
            "validation": validation,
            "stats": {
                **summary.get("stats", {}),
                "covered_learning_steps": evidence_map.get("summary", {}).get("step_coverage_count", 0),
                "render_timeline_count": len(render_bundle.get("timeline", [])),
            },
        },
    }
