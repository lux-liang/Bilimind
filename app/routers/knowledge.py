"""
BiliMind 知识树学习导航系统

知识库路由 - 构建和管理知识库 + 知识抽取 + 图谱构建
"""
from datetime import datetime
from fastapi import APIRouter, HTTPException, Query, BackgroundTasks, Depends
from loguru import logger
from typing import List, Optional, Callable
from pydantic import BaseModel
from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db, get_db_context
from app.models import (
    FavoriteFolder, FavoriteVideo, VideoCache, UserSession,
    ContentSource, VideoContent, Segment, KnowledgeNode, KnowledgeEdge, NodeSegmentLink,
)
from app.services.bilibili import BilibiliService
from app.services.content_fetcher import ContentFetcher, identify_platform
from app.services.asr import ASRService
from app.services.rag import RAGService
from app.services.extractor import KnowledgeExtractor
from app.services.graph_store import GraphStore
from app.services.tree_builder import TreeBuilder
from app.services.graph_rag import GraphRAGService
from app.config import settings
from app.routers.auth import get_session

router = APIRouter(prefix="/knowledge", tags=["知识库"])

# 全局服务实例
_rag_service: Optional[RAGService] = None
_extractor: Optional[KnowledgeExtractor] = None
# 构建任务状态
build_tasks = {}


def get_rag_service() -> RAGService:
    """获取 RAG 服务实例"""
    global _rag_service
    if _rag_service is None:
        _rag_service = RAGService()
    return _rag_service


def get_extractor() -> KnowledgeExtractor:
    global _extractor
    if _extractor is None:
        _extractor = KnowledgeExtractor()
    return _extractor
async def _load_graph_for_session(db: AsyncSession, session_id: Optional[str]) -> GraphStore:
    """为当前用户加载隔离后的图谱快照。"""
    graph = GraphStore(graph_path=settings.graph_persist_path)
    await graph.load_from_db(db, session_id=session_id)
    return graph


def get_graph() -> GraphStore:
    """兼容旧代码：返回一个新的图实例，不复用跨请求单例。"""
    graph = GraphStore(graph_path=settings.graph_persist_path)
    graph.load_json()
    return graph


_graph_rag_service: Optional[GraphRAGService] = None


def get_graph_rag_service(graph_store: Optional[GraphStore] = None) -> GraphRAGService:
    global _graph_rag_service
    if graph_store is not None:
        return GraphRAGService(graph_store)
    if _graph_rag_service is None:
        _graph_rag_service = GraphRAGService(GraphStore(graph_path=settings.graph_persist_path))
    return _graph_rag_service


class BuildRequest(BaseModel):
    """知识库构建请求"""
    folder_ids: List[int]  # 要处理的收藏夹 ID 列表
    exclude_bvids: Optional[List[str]] = None  # 排除的视频


class BuildStatus(BaseModel):
    """构建状态"""
    task_id: str
    status: str  # pending / running / completed / failed
    progress: int  # 0-100
    current_step: str
    total_videos: int
    processed_videos: int
    message: str


class FolderStatus(BaseModel):
    """收藏夹入库状态"""
    media_id: int
    indexed_count: int
    media_count: Optional[int] = None
    last_sync_at: Optional[datetime] = None


class SyncRequest(BaseModel):
    """同步请求"""
    folder_ids: Optional[List[int]] = None


class SyncResult(BaseModel):
    """同步结果"""
    folder_id: int
    total: int
    added: int
    removed: int
    indexed: int
    message: str
    last_sync_at: Optional[datetime] = None


async def _get_or_create_folder(
    db: AsyncSession,
    session_id: str,
    media_id: int,
    title: Optional[str] = None,
    media_count: Optional[int] = None,
) -> FavoriteFolder:
    """获取或创建收藏夹记录"""
    result = await db.execute(
        select(FavoriteFolder).where(
            FavoriteFolder.session_id == session_id,
            FavoriteFolder.media_id == media_id,
        )
    )
    folder = result.scalar_one_or_none()

    if folder is None:
        folder = FavoriteFolder(
            session_id=session_id,
            media_id=media_id,
            title=title or "",
            media_count=media_count or 0,
            is_selected=True,
        )
        db.add(folder)
        await db.flush()
    else:
        if title:
            folder.title = title
        if media_count is not None:
            folder.media_count = media_count

    return folder


def _extract_video_info(media: dict) -> tuple[str, str, Optional[int]]:
    """抽取视频关键信息"""
    bvid = media.get("bvid") or media.get("bv_id")
    title = media.get("title", bvid)
    cid = None
    ugc = media.get("ugc") or {}
    if ugc.get("first_cid"):
        cid = ugc.get("first_cid")
    else:
        cid = media.get("cid") or media.get("id")
    return bvid, title, cid


async def _upsert_video_cache(db: AsyncSession, bvid: str, meta: dict, session_id: Optional[str] = None) -> None:
    """写入或更新视频缓存信息"""
    result = await db.execute(select(VideoCache).where(VideoCache.bvid == bvid))
    cache = result.scalar_one_or_none()

    if cache is None:
        cache = VideoCache(
            bvid=bvid,
            title=meta.get("title") or bvid,
            description=meta.get("intro"),
            owner_name=meta.get("owner_name"),
            owner_mid=meta.get("owner_mid"),
            duration=meta.get("duration"),
            pic_url=meta.get("cover"),
            is_processed=False,
            session_id=session_id,
        )
        db.add(cache)
        return

    cache.title = meta.get("title") or cache.title
    if meta.get("intro") is not None:
        cache.description = meta.get("intro")
    if meta.get("owner_name") is not None:
        cache.owner_name = meta.get("owner_name")
    if meta.get("owner_mid") is not None:
        cache.owner_mid = meta.get("owner_mid")
    if meta.get("duration") is not None:
        cache.duration = meta.get("duration")
    if meta.get("cover") is not None:
        cache.pic_url = meta.get("cover")


async def _sync_folder(
    db: AsyncSession,
    bili: BilibiliService,
    rag: RAGService,
    content_fetcher: ContentFetcher,
    session_id: str,
    folder_id: int,
    exclude_bvids: Optional[set[str]] = None,
    progress_callback: Optional[Callable[[str], None]] = None,
) -> dict:
    """同步单个收藏夹到向量库"""
    info = {}
    try:
        info_result = await bili.get_favorite_content(folder_id, pn=1, ps=1)
        info = info_result.get("info", {})
    except Exception as e:
        logger.warning(f"获取收藏夹信息失败 [{folder_id}]: {e}")

    videos = await bili.get_all_favorite_videos(folder_id)
    total_in_folder = info.get("media_count", len(videos))

    # 保护：接口异常返回空列表时，避免误删
    if not videos:
        if total_in_folder and total_in_folder > 0:
            logger.warning(f"[{folder_id}] 收藏夹返回空列表，跳过删除逻辑")
            folder_row = await db.execute(
                select(FavoriteFolder.id).where(
                    FavoriteFolder.session_id == session_id,
                    FavoriteFolder.media_id == folder_id,
                )
            )
            folder_pk = folder_row.scalar_one_or_none()
            existing_count = 0
            if folder_pk is not None:
                existing_count = await db.scalar(
                    select(func.count(FavoriteVideo.bvid))
                    .where(FavoriteVideo.folder_id == folder_pk)
                )
            return {
                "folder_id": folder_id,
                "total": total_in_folder,
                "added": 0,
                "removed": 0,
                "indexed": existing_count or 0,
                "message": "本次同步异常：空列表，已跳过",
                "last_sync_at": datetime.utcnow(),
            }

    video_map = {}
    skipped_invalid = 0
    for media in videos:
        bvid, title, cid = _extract_video_info(media)
        if not bvid:
            continue
        if exclude_bvids and bvid in exclude_bvids:
            continue
        
        # 过滤失效视频（被删除、下架等）
        # attr 字段: 0=正常, 9=已失效, 1=私密等
        attr = media.get("attr", 0)
        if attr == 9 or title in ["已失效视频", "已删除视频"]:
            skipped_invalid += 1
            logger.debug(f"跳过失效视频: {bvid} - {title}")
            continue
        
        owner = media.get("upper") or {}
        video_map[bvid] = {
            "title": title,
            "cid": cid,
            "intro": media.get("intro"),
            "cover": media.get("cover"),
            "duration": media.get("duration"),
            "owner_name": owner.get("name"),
            "owner_mid": owner.get("mid"),
        }
    
    if skipped_invalid > 0:
        logger.info(f"[{folder_id}] 过滤了 {skipped_invalid} 个失效视频")

    # 以有效视频数作为统计口径（过滤失效视频）
    valid_count = len(video_map)
    current_bvids = set(video_map.keys())

    folder = await _get_or_create_folder(
        db,
        session_id=session_id,
        media_id=folder_id,
        title=info.get("title"),
        media_count=valid_count,
    )

    existing_rows = await db.execute(
        select(FavoriteVideo.bvid).where(FavoriteVideo.folder_id == folder.id)
    )
    existing_bvids = {row[0] for row in existing_rows.fetchall()}

    added = current_bvids - existing_bvids
    removed = existing_bvids - current_bvids

    # 写入标题/简介等信息
    for bvid, meta in video_map.items():
        await _upsert_video_cache(db, bvid, meta, session_id=session_id)

    source_priority = {
        ContentSource.BASIC_INFO.value: 1,
        ContentSource.AI_SUMMARY.value: 2,
        ContentSource.SUBTITLE.value: 3,
        ContentSource.ASR.value: 4,
    }

    def _is_better_source(new_source: str, old_source: Optional[str]) -> bool:
        return source_priority.get(new_source, 0) > source_priority.get(old_source or "", 0)

    def _should_refresh_cache(cache: Optional[VideoCache]) -> bool:
        if not cache:
            return True
        text = (cache.content or "").strip()
        if len(text) < 50:
            return True
        if cache.content_source in (None, "", ContentSource.BASIC_INFO.value):
            return True
        return False

    def _is_asr_cache_usable(cache: Optional[VideoCache]) -> bool:
        if not cache:
            return False
        if cache.content_source != ContentSource.ASR.value:
            return False
        text = (cache.content or "").strip()
        return len(text) >= 50

    # 需要更新的已存在视频（缓存过少或来源较弱）
    update_candidates: set[str] = set()
    for bvid in current_bvids & existing_bvids:
        if bvid in added:
            continue
        result = await db.execute(select(VideoCache).where(VideoCache.bvid == bvid))
        cache = result.scalar_one_or_none()
        if _should_refresh_cache(cache):
            update_candidates.add(bvid)
            continue

        # 若该视频已有片段但没有任何知识节点关联，加入重处理队列以便重跑抽取。
        link_query = select(func.count()).select_from(NodeSegmentLink).where(
            NodeSegmentLink.video_bvid == bvid
        )
        if session_id:
            link_query = link_query.where(NodeSegmentLink.session_id == session_id)
        link_count = await db.scalar(link_query)
        if (link_count or 0) == 0:
            update_candidates.add(bvid)

    # 新增/更新向量与关联
    targets = list(added) + list(update_candidates)
    total_targets = len(targets)
    processed_targets = 0
    if progress_callback:
        progress_callback("准备处理", processed_targets, total_targets)
    for bvid in targets:
        meta = video_map[bvid]
        
        # 尝试添加到向量库（可能失败，但不影响记录入库）
        try:
            global_count = await db.scalar(
                select(func.count())
                .select_from(FavoriteVideo)
                .join(FavoriteFolder, FavoriteVideo.folder_id == FavoriteFolder.id)
                .where(
                    FavoriteVideo.bvid == bvid,
                    FavoriteFolder.session_id == session_id,
                )
            )
            # 检查缓存内容是否缺失
            result = await db.execute(select(VideoCache).where(VideoCache.bvid == bvid))
            cache = result.scalar_one_or_none()
            old_content = (cache.content or "").strip() if cache else ""
            old_source = cache.content_source if cache else None

            needs_fetch = _should_refresh_cache(cache)
            content = None
            should_update_cache = False
            should_reindex = False

            if needs_fetch:
                content = await content_fetcher.fetch_content(
                    bvid, cid=meta["cid"], title=meta["title"]
                )
                new_text = (content.content or "").strip() if content else ""
                new_source = content.source.value if content else None

                if not old_content:
                    should_update_cache = True
                    should_reindex = True
                elif new_source and _is_better_source(new_source, old_source):
                    should_update_cache = True
                    should_reindex = True
                elif new_text and new_text != old_content:
                    should_update_cache = True
                    should_reindex = True

                if cache and should_update_cache:
                    cache.content = content.content
                    cache.content_source = content.source.value
                    cache.outline_json = content.outline
                    cache.is_processed = True
                    logger.info(f"[{bvid}] 已写入缓存: source={cache.content_source}")

            # 需要重建向量：新增/升级/内容变化 或 向量缺失
            if (global_count == 0) or should_reindex:
                if not content:
                    if _is_asr_cache_usable(cache):
                        content = VideoContent(
                            bvid=bvid,
                            title=meta["title"],
                            content=(cache.content or "").strip(),
                            source=ContentSource.ASR,
                            outline=cache.outline_json,
                        )
                        cache.is_processed = True
                        logger.info(f"[{bvid}] 使用缓存 ASR 内容重建向量")
                    else:
                        content = await content_fetcher.fetch_content(
                            bvid, cid=meta["cid"], title=meta["title"]
                        )
                        if cache:
                            cache.content = content.content
                            cache.content_source = content.source.value
                            cache.outline_json = content.outline
                            cache.is_processed = True
                            logger.info(f"[{bvid}] 已写入缓存: source={cache.content_source}")
                try:
                    rag.delete_video(bvid, session_id=session_id)
                except Exception as e:
                    logger.warning(f"删除旧向量失败 [{bvid}]: {e}")
                chunks = rag.add_video_content(content, session_id=session_id)
                logger.info(f"[{bvid}] 向量化完成，块数={chunks}")
            else:
                logger.info(f"[{bvid}] 内容未变化或无需升级，跳过向量化")
        except Exception as e:
            logger.warning(f"添加向量失败 [{bvid}]: {e} (仍会记录到数据库)")

        # === 知识抽取 pipeline ===
        try:
            await _extract_knowledge_for_video(
                db, content_fetcher, bvid, meta, cache, session_id=session_id
            )
        except Exception as e:
            logger.warning(f"知识抽取失败 [{bvid}]: {e} (不影响主流程)")
        
        # 无论向量是否添加成功，都写入 FavoriteVideo 记录
        try:
            exists_row = await db.execute(
                select(FavoriteVideo.id).where(
                    FavoriteVideo.folder_id == folder.id,
                    FavoriteVideo.bvid == bvid,
                )
            )
            if exists_row.scalar_one_or_none() is None:
                db.add(FavoriteVideo(folder_id=folder.id, bvid=bvid, is_selected=True))
            processed_targets += 1
            if progress_callback:
                progress_callback(meta["title"], processed_targets, total_targets)
        except Exception as e:
            logger.error(f"写入数据库失败 [{bvid}]: {e}")

    # 删除无效向量
    if removed:
        for bvid in removed:
            other_count = await db.scalar(
                select(func.count())
                .select_from(FavoriteVideo)
                .join(FavoriteFolder, FavoriteVideo.folder_id == FavoriteFolder.id)
                .where(
                    FavoriteVideo.bvid == bvid,
                    FavoriteVideo.folder_id != folder.id,
                    FavoriteFolder.session_id == session_id,
                )
            )
            if other_count == 0:
                try:
                    rag.delete_video(bvid, session_id=session_id)
                except Exception as e:
                    logger.warning(f"删除向量失败 [{bvid}]: {e}")

        await db.execute(
            delete(FavoriteVideo).where(
                FavoriteVideo.folder_id == folder.id,
                FavoriteVideo.bvid.in_(removed),
            )
        )

    folder.last_sync_at = datetime.utcnow()

    await db.commit()

    indexed_count = await db.scalar(
        select(func.count(func.distinct(FavoriteVideo.bvid)))
        .select_from(FavoriteVideo)
        .where(FavoriteVideo.folder_id == folder.id)
    )

    return {
        "folder_id": folder_id,
        "total": valid_count,
        "added": len(added),
        "removed": len(removed),
        "indexed": indexed_count or 0,
        "message": "同步完成",
        "last_sync_at": folder.last_sync_at,
    }


async def _reset_session_knowledge_data(
    db: AsyncSession,
    rag: RAGService,
    session_id: str,
) -> None:
    """清理当前会话旧知识数据，保证知识树仅反映本次选择的收藏夹。"""
    folder_rows = await db.execute(
        select(FavoriteFolder.id).where(FavoriteFolder.session_id == session_id)
    )
    folder_ids = [row[0] for row in folder_rows.fetchall()]

    if folder_ids:
        await db.execute(
            delete(FavoriteVideo).where(FavoriteVideo.folder_id.in_(folder_ids))
        )

    await db.execute(delete(FavoriteFolder).where(FavoriteFolder.session_id == session_id))
    await db.execute(delete(NodeSegmentLink).where(NodeSegmentLink.session_id == session_id))
    await db.execute(delete(KnowledgeEdge).where(KnowledgeEdge.session_id == session_id))
    await db.execute(delete(KnowledgeNode).where(KnowledgeNode.session_id == session_id))
    await db.execute(delete(Segment).where(Segment.session_id == session_id))

    await db.commit()

    try:
        rag.clear_collection(session_id=session_id)
    except Exception as e:
        logger.warning(f"清理向量库失败 [{session_id}]: {e}")


@router.get("/stats")
async def get_knowledge_stats(
    session_id: Optional[str] = Query(None, description="会话ID，用于数据隔离"),
):
    """获取知识库统计信息"""
    try:
        rag = get_rag_service()
        stats = rag.get_collection_stats(session_id=session_id)
        return stats
    except Exception as e:
        logger.error(f"获取统计信息失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/folders/status", response_model=List[FolderStatus])
async def get_folder_status(
    session_id: str = Query(..., description="会话ID"),
    db: AsyncSession = Depends(get_db),
):
    """获取当前 session 的收藏夹入库状态。"""

    rows = await db.execute(
        select(FavoriteFolder.id, FavoriteFolder.media_id, FavoriteFolder.last_sync_at)
        .where(FavoriteFolder.session_id == session_id)
        .order_by(FavoriteFolder.updated_at.desc())
    )
    
    # 手动按 media_id 去重，保留最新的
    folders_map = {}
    for row in rows.fetchall():
        fid, media_id, last_sync = row
        if media_id not in folders_map:
            folders_map[media_id] = (fid, last_sync)
            
    if not folders_map:
        return []

    folder_ids = [v[0] for v in folders_map.values()]
    
    # 4. 统计视频数量
    counts = await db.execute(
        select(FavoriteVideo.folder_id, func.count(func.distinct(FavoriteVideo.bvid)))
        .where(FavoriteVideo.folder_id.in_(folder_ids))
        .group_by(FavoriteVideo.folder_id)
    )
    count_map = {row[0]: row[1] for row in counts.fetchall()}

    result = []
    for media_id, (folder_id, last_sync_at) in folders_map.items():
        # 读取有效视频数（过滤失效后的口径）
        folder_row = await db.execute(
            select(FavoriteFolder.media_count).where(FavoriteFolder.id == folder_id)
        )
        media_count = folder_row.scalar()
        result.append(
            FolderStatus(
                media_id=media_id,
                indexed_count=count_map.get(folder_id, 0),
                media_count=media_count,
                last_sync_at=last_sync_at,
            )
        )
    return result


@router.post("/folders/sync", response_model=List[SyncResult])
async def sync_folders(
    request: SyncRequest,
    session_id: str = Query(..., description="会话ID"),
    db: AsyncSession = Depends(get_db),
):
    """同步收藏夹到向量库"""
    session = await get_session(session_id)
    if not session:
        raise HTTPException(status_code=401, detail="未登录或会话已过期")

    cookies = session.get("cookies", {})
    user_info = session.get("user_info", {})

    bili = BilibiliService(
        sessdata=cookies.get("SESSDATA"),
        bili_jct=cookies.get("bili_jct"),
        dedeuserid=cookies.get("DedeUserID"),
    )
    rag = get_rag_service()
    asr_service = ASRService()
    content_fetcher = ContentFetcher(bili, asr_service)

    try:
        folder_ids = request.folder_ids or []
        if not folder_ids:
            mid = user_info.get("mid") or cookies.get("DedeUserID")
            if not mid:
                raise HTTPException(status_code=400, detail="无法获取用户信息")
            folders = await bili.get_user_favorites(mid=mid)
            folder_ids = [folder.get("id") for folder in folders if folder.get("id")]

        results: List[SyncResult] = []
        for folder_id in folder_ids:
            try:
                result = await _sync_folder(
                    db,
                    bili,
                    rag,
                    content_fetcher,
                    session_id,
                    folder_id,
                )
                results.append(SyncResult(**result))
            except Exception as e:
                logger.error(f"同步收藏夹失败 [{folder_id}]: {e}")
                results.append(
                    SyncResult(
                        folder_id=folder_id,
                        total=0,
                        added=0,
                        removed=0,
                        indexed=0,
                        message=f"同步失败: {e}",
                        last_sync_at=None,
                    )
                )

        return results
    finally:
        await bili.close()


@router.post("/build")
async def build_knowledge_base(
    request: BuildRequest,
    background_tasks: BackgroundTasks,
    session_id: str = Query(..., description="会话ID"),
):
    """构建知识库（后台任务）"""
    session = await get_session(session_id)
    if not session:
        raise HTTPException(status_code=401, detail="未登录或会话已过期")

    import uuid
    task_id = str(uuid.uuid4())

    build_tasks[task_id] = {
        "status": "pending",
        "progress": 0,
        "current_step": "初始化中...",
        "total_videos": 0,
        "processed_videos": 0,
        "message": "",
        "session_id": session_id,
        "dataset_version": str(uuid.uuid4()),
    }

    background_tasks.add_task(
        _build_knowledge_base_task,
        task_id,
        session_id,
        session,
        request.folder_ids,
        request.exclude_bvids or [],
    )

    return {"task_id": task_id, "message": "构建任务已启动"}


async def _build_knowledge_base_task(
    task_id: str,
    session_id: str,
    session: dict,
    folder_ids: List[int],
    exclude_bvids: List[str],
):
    """后台构建任务"""
    cookies = session.get("cookies", {})

    try:
        build_tasks[task_id]["status"] = "running"
        build_tasks[task_id]["current_step"] = "同步收藏夹..."

        bili = BilibiliService(
            sessdata=cookies.get("SESSDATA"),
            bili_jct=cookies.get("bili_jct"),
            dedeuserid=cookies.get("DedeUserID"),
        )
        asr_service = ASRService()
        content_fetcher = ContentFetcher(bili, asr_service)
        rag = get_rag_service()

        try:
            total_folders = len(folder_ids)
            if total_folders == 0:
                build_tasks[task_id]["status"] = "completed"
                build_tasks[task_id]["progress"] = 100
                build_tasks[task_id]["message"] = "没有需要处理的收藏夹"
                return

            processed = 0
            total_added = 0
            total_removed = 0

            async with get_db_context() as db:
                build_tasks[task_id]["current_step"] = "清理历史数据..."
                build_tasks[task_id]["progress"] = 3
                await _reset_session_knowledge_data(db, rag, session_id)

                for idx, folder_id in enumerate(folder_ids, start=1):
                    build_tasks[task_id]["current_step"] = f"同步收藏夹 {folder_id}"

                    def progress_cb(title: str, processed_count: int = 0, total_count: int = 0):
                        build_tasks[task_id]["current_step"] = f"处理: {title}"
                        if total_count:
                            build_tasks[task_id]["total_videos"] = total_count
                        if processed_count:
                            build_tasks[task_id]["processed_videos"] = processed_count
                            if build_tasks[task_id]["total_videos"]:
                                build_tasks[task_id]["progress"] = int(
                                    (processed_count / build_tasks[task_id]["total_videos"]) * 100
                                )

                    result = await _sync_folder(
                        db,
                        bili,
                        rag,
                        content_fetcher,
                        session_id,
                        folder_id,
                        exclude_bvids=set(exclude_bvids),
                        progress_callback=progress_cb,
                    )

                    processed = idx
                    total_added += result["added"]
                    total_removed += result["removed"]

            build_tasks[task_id]["status"] = "completed"
            build_tasks[task_id]["progress"] = 100
            build_tasks[task_id]["processed_videos"] = total_folders
            build_tasks[task_id]["current_step"] = "完成"
            build_tasks[task_id]["message"] = f"同步完成：新增 {total_added}，移除 {total_removed}"

            logger.info(f"知识库构建完成: 新增 {total_added}，移除 {total_removed}")
        finally:
            await bili.close()

    except Exception as e:
        logger.error(f"构建任务失败: {e}")
        build_tasks[task_id]["status"] = "failed"
        build_tasks[task_id]["message"] = str(e)


@router.get("/build/status/{task_id}", response_model=BuildStatus)
async def get_build_status(
    task_id: str,
    session_id: str = Query(..., description="会话ID"),
):
    """获取构建任务状态"""
    if task_id not in build_tasks:
        raise HTTPException(status_code=404, detail="任务不存在")

    task = build_tasks[task_id]
    if task.get("session_id") != session_id:
        raise HTTPException(status_code=404, detail="任务不存在")
    return BuildStatus(
        task_id=task_id,
        status=task["status"],
        progress=task["progress"],
        current_step=task["current_step"],
        total_videos=task["total_videos"],
        processed_videos=task["processed_videos"],
        message=task["message"],
    )


@router.delete("/clear")
async def clear_knowledge_base(
    session_id: Optional[str] = Query(None, description="会话ID，用于数据隔离"),
):
    """清空知识库"""
    try:
        rag = get_rag_service()
        rag.clear_collection(session_id=session_id)
        return {"message": "知识库已清空"}
    except Exception as e:
        logger.error(f"清空知识库失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/video/{bvid}")
async def delete_video_from_knowledge(
    bvid: str,
    session_id: Optional[str] = Query(None, description="会话ID，用于数据隔离"),
):
    """从知识库中删除指定视频"""
    try:
        rag = get_rag_service()
        rag.delete_video(bvid, session_id=session_id)
        return {"message": f"已删除视频 {bvid}"}
    except Exception as e:
        logger.error(f"删除视频失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== 知识抽取 Pipeline ====================

async def _extract_knowledge_for_video(
    db: AsyncSession,
    content_fetcher: ContentFetcher,
    bvid: str,
    meta: dict,
    cache: Optional[VideoCache],
    session_id: Optional[str] = None,
) -> None:
    """
    对单个视频执行知识抽取：
    1. 获取/创建 Segment
    2. LLM 抽取实体和关系
    3. 写入图存储 + SQLite
    """
    segment_records: list[Segment] = []

    # 检查是否已有片段，并决定是否可以直接复用
    existing_segment_query = select(Segment).where(Segment.video_bvid == bvid)
    if session_id:
        existing_segment_query = existing_segment_query.where(Segment.session_id == session_id)
    existing_segment_query = existing_segment_query.order_by(Segment.segment_index.asc(), Segment.id.asc())
    existing_segment_rows = await db.execute(existing_segment_query)
    existing_segments = existing_segment_rows.scalars().all()

    if existing_segments:
        done_query = (
            select(func.count()).select_from(Segment)
            .where(Segment.video_bvid == bvid, Segment.extraction_status == "done")
        )
        if session_id:
            done_query = done_query.where(Segment.session_id == session_id)
        done_count = await db.scalar(done_query)

        if done_count and done_count > 0:
            link_query = select(func.count()).select_from(NodeSegmentLink).where(NodeSegmentLink.video_bvid == bvid)
            if session_id:
                link_query = link_query.where(NodeSegmentLink.session_id == session_id)
            link_count = await db.scalar(link_query)
            if (link_count or 0) > 0:
                logger.info(f"[{bvid}] 已完成知识抽取，跳过")
                return
            logger.info(f"[{bvid}] 片段已存在但无节点关联，重试知识抽取")

        segment_records = existing_segments

    # Step 1: 无可复用片段时，重新获取并写入 Segment
    if not segment_records:
        segments_data = await content_fetcher.fetch_segments(
            bvid, cid=meta.get("cid"), title=meta.get("title"),
            duration=meta.get("duration"),
        )

        if not segments_data:
            logger.info(f"[{bvid}] 无法获取片段，跳过知识抽取")
            return

        for seg in segments_data:
            record = Segment(
                video_bvid=bvid,
                segment_index=seg["segment_index"],
                start_time=seg.get("start_time"),
                end_time=seg.get("end_time"),
                raw_text=seg["raw_text"],
                cleaned_text=seg["raw_text"],  # 暂不做额外清洗
                source_type=seg.get("source_type", "unknown"),
                confidence=seg.get("confidence", 0.5),
                extraction_status="pending",
                session_id=session_id,
            )
            db.add(record)
            segment_records.append(record)

        await db.flush()  # 获取 ID

    # Step 2: 知识抽取
    extractor = get_extractor()
    extract_input = [
        {
            "text": seg.raw_text,
            "segment_id": seg.id,
            "video_bvid": bvid,
        }
        for seg in segment_records
    ]

    result = await extractor.extract_from_segments(extract_input, meta.get("title", ""))
    entities = result.get("entities", [])
    relations = result.get("relations", [])

    if not entities:
        for seg in segment_records:
            seg.extraction_status = "done"
        await db.commit()
        logger.info(f"[{bvid}] 未抽取到知识实体")
        return

    # Step 3: 写入图存储
    graph = await _load_graph_for_session(db, session_id)
    name_to_node_id: dict[str, int] = {}

    for entity in entities:
        normalized = entity.get("normalized_name", entity["name"].lower().strip())

        # 查找已有节点
        existing_id = graph.find_node_by_name(normalized)
        if existing_id is not None:
            # 更新 source_count
            node_data = graph.get_node(existing_id)
            if node_data:
                new_count = node_data.get("source_count", 1) + 1
                graph.graph.nodes[existing_id]["source_count"] = new_count
                graph.graph.nodes[existing_id]["confidence"] = max(
                    node_data.get("confidence", 0), entity.get("confidence", 0.5)
                )
                # 更新 difficulty（取更大值，LLM 推断覆盖默认值）
                new_difficulty = entity.get("difficulty", 1)
                if new_difficulty > node_data.get("difficulty", 1):
                    graph.graph.nodes[existing_id]["difficulty"] = new_difficulty
                # 同步到 DB
                db_query = select(KnowledgeNode).where(KnowledgeNode.id == existing_id)
                if session_id:
                    db_query = db_query.where(KnowledgeNode.session_id == session_id)
                db_result = await db.execute(db_query)
                db_node = db_result.scalar_one_or_none()
                if db_node:
                    db_node.source_count = new_count
                    db_node.confidence = graph.graph.nodes[existing_id]["confidence"]
                    if new_difficulty > db_node.difficulty:
                        db_node.difficulty = new_difficulty
            name_to_node_id[normalized] = existing_id
        else:
            # 创建新节点
            node = await graph.sync_node_to_db(db, None, {
                "node_type": entity.get("type", "concept"),
                "name": entity["name"],
                "normalized_name": normalized,
                "definition": entity.get("definition", ""),
                "difficulty": entity.get("difficulty", 1),
                "confidence": entity.get("confidence", 0.5),
                "source_count": entity.get("source_count", 1),
                "review_status": "auto" if entity.get("confidence", 0) >= settings.tree_min_confidence else "pending_review",
                "session_id": session_id,
            })
            graph.add_node(node.id, **{
                "node_type": node.node_type,
                "name": node.name,
                "normalized_name": node.normalized_name,
                "definition": node.definition,
                "difficulty": node.difficulty,
                "confidence": node.confidence,
                "source_count": node.source_count,
                "review_status": node.review_status,
            })
            name_to_node_id[normalized] = node.id

        # 创建 NodeSegmentLink
        for seg_id in entity.get("_segment_ids", []):
            if seg_id:
                db.add(NodeSegmentLink(
                    node_id=name_to_node_id[normalized],
                    segment_id=seg_id,
                    video_bvid=bvid,
                    relation="mentions",
                    confidence=entity.get("confidence", 0.5),
                    session_id=session_id,
                ))

    # 写入关系
    for rel in relations:
        src_norm = rel.get("source_normalized", rel["source"].lower().strip())
        tgt_norm = rel.get("target_normalized", rel["target"].lower().strip())
        src_id = name_to_node_id.get(src_norm)
        tgt_id = name_to_node_id.get(tgt_norm)
        if src_id and tgt_id and src_id != tgt_id:
            graph.add_edge(src_id, tgt_id, **{
                "relation_type": rel["type"],
                "weight": 1.0,
                "confidence": rel.get("confidence", 0.5),
                "evidence_video_bvid": bvid,
                "evidence_segment_id": rel.get("_segment_id"),
            })
            await graph.sync_edge_to_db(db, src_id, tgt_id, {
                "relation_type": rel["type"],
                "weight": 1.0,
                "confidence": rel.get("confidence", 0.5),
                "evidence_video_bvid": bvid,
                "evidence_segment_id": rel.get("_segment_id"),
                "session_id": session_id,
            })

    # 更新 segment 状态
    for seg in segment_records:
        seg.extraction_status = "done"

    # 更新 VideoCache
    if cache:
        cache.extraction_status = "done"
        cache.knowledge_node_count = len(entities)

    await db.commit()

    logger.info(f"[{bvid}] 知识抽取完成: {len(entities)} 实体, {len(relations)} 关系")


# ==================== 跨平台 URL 导入 ====================

class ImportUrlRequest(BaseModel):
    """URL 导入请求"""
    url: str
    session_id: Optional[str] = None


class ImportUrlResponse(BaseModel):
    """URL 导入响应"""
    source_id: str
    source_type: str
    title: str
    content_length: int
    segment_count: int
    node_count: int


@router.post("/import-url", response_model=ImportUrlResponse)
async def import_url(
    request: ImportUrlRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    通过 URL 导入内容（支持 B站/知乎/小红书）

    自动识别平台 → 抓取内容 → 写入缓存 → 知识抽取 → 写入图谱
    """
    url = request.url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="URL 不能为空")

    platform, params = identify_platform(url)
    if platform == "unknown":
        raise HTTPException(status_code=400, detail=f"不支持的 URL 格式: {url}")

    # 创建 ContentFetcher（对 bilibili 需要 BilibiliService）
    if platform == "bilibili":
        session = None
        if request.session_id:
            session = await get_session(request.session_id)
        cookies = (session or {}).get("cookies", {})
        bili = BilibiliService(
            sessdata=cookies.get("SESSDATA"),
            bili_jct=cookies.get("bili_jct"),
            dedeuserid=cookies.get("DedeUserID"),
        )
        asr_service = ASRService()
        content_fetcher = ContentFetcher(bili, asr_service)
    else:
        # 非 B站平台不需要 BilibiliService
        content_fetcher = ContentFetcher(
            bilibili_service=None,  # type: ignore
            asr_service=None,  # type: ignore
        )

    try:
        content, segments_data = await content_fetcher.fetch_from_url(url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"URL 导入失败 [{url}]: {e}")
        raise HTTPException(status_code=500, detail=f"内容获取失败: {e}")
    finally:
        if platform == "bilibili":
            await bili.close()

    source_id = content.bvid
    source_type_str = content.source_type.value if hasattr(content.source_type, 'value') else str(content.source_type)

    # 写入 VideoCache
    result = await db.execute(select(VideoCache).where(VideoCache.bvid == source_id))
    cache = result.scalar_one_or_none()
    if cache is None:
        cache = VideoCache(
            bvid=source_id,
            title=content.title,
            content=content.content,
            content_source=content.source.value,
            source_type=source_type_str,
            source_url=url,
            is_processed=True,
            session_id=request.session_id,
        )
        db.add(cache)
    else:
        cache.content = content.content
        cache.content_source = content.source.value
        cache.source_type = source_type_str
        cache.source_url = url
        cache.is_processed = True

    await db.flush()

    # 写入 Segment 表
    segment_records = []
    for seg in segments_data:
        record = Segment(
            video_bvid=source_id,
            segment_index=seg["segment_index"],
            start_time=seg.get("start_time"),
            end_time=seg.get("end_time"),
            raw_text=seg["raw_text"],
            cleaned_text=seg["raw_text"],
            source_type=seg.get("source_type", "text_paragraph"),
            confidence=seg.get("confidence", 0.8),
            extraction_status="pending",
            session_id=request.session_id,
        )
        db.add(record)
        segment_records.append(record)
    await db.flush()

    # 写入 RAG 向量库
    rag = get_rag_service()
    try:
        rag.delete_video(source_id, session_id=request.session_id)
    except Exception:
        pass
    try:
        chunks = rag.add_video_content(content, session_id=request.session_id)
        logger.info(f"[{source_id}] 向量化完成，块数={chunks}")
    except Exception as e:
        logger.warning(f"[{source_id}] 向量化失败: {e}")

    # 知识抽取
    node_count = 0
    try:
        extractor = get_extractor()
        extract_input = [
            {
                "text": seg.raw_text,
                "segment_id": seg.id,
                "video_bvid": source_id,
            }
            for seg in segment_records
        ]
        result_data = await extractor.extract_from_segments(extract_input, content.title)
        entities = result_data.get("entities", [])
        relations = result_data.get("relations", [])

        if entities:
            graph = await _load_graph_for_session(db, request.session_id)
            name_to_node_id: dict[str, int] = {}

            for entity in entities:
                normalized = entity.get("normalized_name", entity["name"].lower().strip())
                existing_id = graph.find_node_by_name(normalized)
                if existing_id is not None:
                    node_data = graph.get_node(existing_id)
                    if node_data:
                        new_count = node_data.get("source_count", 1) + 1
                        graph.graph.nodes[existing_id]["source_count"] = new_count
                        graph.graph.nodes[existing_id]["confidence"] = max(
                            node_data.get("confidence", 0), entity.get("confidence", 0.5)
                        )
                        db_query = select(KnowledgeNode).where(KnowledgeNode.id == existing_id)
                        if request.session_id:
                            db_query = db_query.where(KnowledgeNode.session_id == request.session_id)
                        db_result = await db.execute(db_query)
                        db_node = db_result.scalar_one_or_none()
                        if db_node:
                            db_node.source_count = new_count
                            db_node.confidence = graph.graph.nodes[existing_id]["confidence"]
                    name_to_node_id[normalized] = existing_id
                else:
                    node = await graph.sync_node_to_db(db, None, {
                        "node_type": entity.get("type", "concept"),
                        "name": entity["name"],
                        "normalized_name": normalized,
                        "definition": entity.get("definition", ""),
                        "difficulty": entity.get("difficulty", 1),
                        "confidence": entity.get("confidence", 0.5),
                        "source_count": entity.get("source_count", 1),
                        "review_status": "auto" if entity.get("confidence", 0) >= settings.tree_min_confidence else "pending_review",
                        "session_id": request.session_id,
                    })
                    graph.add_node(node.id, **{
                        "node_type": node.node_type,
                        "name": node.name,
                        "normalized_name": node.normalized_name,
                        "definition": node.definition,
                        "difficulty": node.difficulty,
                        "confidence": node.confidence,
                        "source_count": node.source_count,
                        "review_status": node.review_status,
                    })
                    name_to_node_id[normalized] = node.id

                for seg_id in entity.get("_segment_ids", []):
                    if seg_id:
                        db.add(NodeSegmentLink(
                            node_id=name_to_node_id[normalized],
                            segment_id=seg_id,
                            video_bvid=source_id,
                            relation="mentions",
                            confidence=entity.get("confidence", 0.5),
                            session_id=request.session_id,
                        ))

            for rel in relations:
                src_norm = rel.get("source_normalized", rel["source"].lower().strip())
                tgt_norm = rel.get("target_normalized", rel["target"].lower().strip())
                src_id = name_to_node_id.get(src_norm)
                tgt_id = name_to_node_id.get(tgt_norm)
                if src_id and tgt_id and src_id != tgt_id:
                    graph.add_edge(src_id, tgt_id, **{
                        "relation_type": rel["type"],
                        "weight": 1.0,
                        "confidence": rel.get("confidence", 0.5),
                        "evidence_video_bvid": source_id,
                        "evidence_segment_id": rel.get("_segment_id"),
                    })
                    await graph.sync_edge_to_db(db, src_id, tgt_id, {
                        "relation_type": rel["type"],
                        "weight": 1.0,
                        "confidence": rel.get("confidence", 0.5),
                        "evidence_video_bvid": source_id,
                        "evidence_segment_id": rel.get("_segment_id"),
                        "session_id": request.session_id,
                    })
            node_count = len(entities)

        for seg in segment_records:
            seg.extraction_status = "done"
        cache.extraction_status = "done"
        cache.knowledge_node_count = node_count

    except Exception as e:
        logger.warning(f"[{source_id}] 知识抽取失败: {e}")

    await db.commit()

    return ImportUrlResponse(
        source_id=source_id,
        source_type=source_type_str,
        title=content.title,
        content_length=len(content.content),
        segment_count=len(segments_data),
        node_count=node_count,
    )


@router.post("/build-communities")
async def build_communities(
    force: bool = Query(False, description="强制重建社区"),
    session_id: Optional[str] = Query(None, description="会话ID，用于数据隔离"),
    db: AsyncSession = Depends(get_db),
):
    """
    运行 GraphRAG 社区检测 + 生成社区摘要

    在知识库构建完成后调用，为 RAG 问答提供图谱级上下文增强
    """
    try:
        graph = await _load_graph_for_session(db, session_id)
        graph_rag = get_graph_rag_service(graph)
        result = await graph_rag.build_communities(force=force)
        return result
    except Exception as e:
        logger.error(f"社区构建失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
