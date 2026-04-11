"""
知映 ZhiYing — 知识编译路由

提供视频知识编译的 API 端点：
- POST /compile/video  — 启动编译（后台任务）
- GET  /compile/status/{task_id} — 查询编译进度
- GET  /compile/result/{bvid}  — 获取编译结果
"""
import uuid
import asyncio
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, BackgroundTasks, Depends
from loguru import logger
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db, get_db_context
from app.config import settings
from app.models import (
    Concept, Claim, ConceptRelation, Segment, VideoCache,
)
from app.services.knowledge_compiler import compile_video, _fmt_time
from app.services.bilibili import BilibiliService
from app.services.content_fetcher import ContentFetcher
from app.services.asr import ASRService
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
    if not settings.openai_api_key:
        raise HTTPException(
            status_code=503,
            detail="未配置 LLM API Key。请在项目根目录 .env 设置 DASHSCOPE_API_KEY 或 OPENAI_API_KEY 后重启后端。",
        )

    # 限制同一 session 的并发编译任务，避免 SQLite 写锁冲突
    for existing_task_id, task in compile_tasks.items():
        if task.get("session_id") == request.session_id and task.get("status") == "running":
            return CompileTaskResponse(
                task_id=existing_task_id,
                message="已有编译任务进行中，请等待完成后再发起新任务",
            )

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

            async def report_progress(progress: float, message: str):
                task = compile_tasks.get(task_id)
                if not task:
                    return
                # 避免回退进度，UI 观感更稳定
                task["progress"] = max(float(task.get("progress", 0.0)), float(progress))
                task["message"] = message

            # 数据库写锁冲突时进行短重试，提升 SQLite 下并发稳定性
            last_error: Optional[Exception] = None
            result = None
            for attempt in range(3):
                try:
                    async with get_db_context() as db:
                        result = await compile_video(
                            db=db,
                            bvid=bvid,
                            session_id=session_id,
                            content_fetcher=content_fetcher,
                            progress_callback=report_progress,
                        )
                    break
                except Exception as e:
                    last_error = e
                    if "database is locked" not in str(e).lower() or attempt == 2:
                        raise
                    wait_s = 1.0 + attempt * 1.2
                    logger.warning(f"[{bvid}] SQLite 写锁冲突，{wait_s:.1f}s 后重试({attempt + 1}/3)")
                    await asyncio.sleep(wait_s)

            if result is None and last_error is not None:
                raise last_error

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
        message = str(e)
        lowered = message.lower()
        if "database is locked" in lowered:
            message = "数据库忙（SQLite 写锁冲突）。请稍后重试，或避免同时执行“构建知识树”和“编译视频”。"
        if "invalid_api_key" in lowered or "incorrect api key" in lowered or "鉴权失败" in message:
            message = "LLM API Key 无效，请检查 DASHSCOPE_API_KEY / OPENAI_API_KEY 并重启后端。"
        compile_tasks[task_id]["status"] = "failed"
        compile_tasks[task_id]["progress"] = 0.0
        compile_tasks[task_id]["message"] = f"编译失败: {message}"


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
    # 读取视频缓存信息（可能不存在，例如直接编译未缓存视频）
    vc_result = await db.execute(
        select(VideoCache).where(VideoCache.bvid == bvid)
    )
    video_cache = vc_result.scalar_one_or_none()

    # 获取与此视频关联的 Claims
    claim_rows = await db.execute(
        select(Claim).where(
            Claim.video_bvid == bvid,
            Claim.session_id == session_id,
        )
    )
    all_claims = claim_rows.scalars().all()

    # 获取 Segments（时间轴）
    seg_rows = await db.execute(
        select(Segment).where(
            Segment.video_bvid == bvid,
            Segment.session_id == session_id,
        ).order_by(Segment.segment_index)
    )
    segments = seg_rows.scalars().all()

    # 当不存在缓存且无任何编译产物时，视为未编译
    if not video_cache and not all_claims and not segments:
        raise HTTPException(status_code=404, detail="视频未编译")

    # 获取 Concepts
    concept_rows = await db.execute(
        select(Concept).where(Concept.session_id == session_id)
    )
    all_concepts = concept_rows.scalars().all()

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
    inferred_duration = None
    if segments:
        ends = [seg.end_time for seg in segments if seg.end_time is not None]
        if ends:
            inferred_duration = int(max(ends))

    video_title = (video_cache.title if video_cache else None) or bvid
    video_duration = video_cache.duration if video_cache else inferred_duration

    return {
        "video": {
            "bvid": bvid,
            "title": video_title,
            "duration": video_duration,
        },
        "concepts": concepts_response,
        "timeline": timeline,
        "prerequisites": prerequisites_response,
        "stats": {
            "concept_count": len(relevant_concepts),
            "claim_count": len(all_claims),
            "peak_count": peak_count,
        },
    }
