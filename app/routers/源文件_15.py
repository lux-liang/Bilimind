"""
收藏整理分类中心路由
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.routers.auth import get_session
from app.services.video_organizer import VideoOrganizerService

router = APIRouter(prefix="/organizer", tags=["收藏整理分类中心"])


@router.get("/report")
async def get_organizer_report(
    session_id: str = Query(..., description="会话ID"),
    folder_ids: Optional[str] = Query(None, description="逗号分隔的收藏夹 media_id 列表"),
    db: AsyncSession = Depends(get_db),
):
    session = await get_session(session_id)
    if not session:
        raise HTTPException(status_code=401, detail="未登录或会话已过期")

    parsed_folder_ids = None
    if folder_ids:
        parsed_folder_ids = [int(item) for item in folder_ids.split(",") if item.strip().isdigit()]

    service = VideoOrganizerService(db)
    report = await service.build_report(session_id=session_id, folder_ids=parsed_folder_ids)
    return report


@router.get("/export")
async def export_organizer_report(
    session_id: str = Query(..., description="会话ID"),
    format: str = Query("json", pattern="^(json|markdown)$"),
    db: AsyncSession = Depends(get_db),
):
    session = await get_session(session_id)
    if not session:
        raise HTTPException(status_code=401, detail="未登录或会话已过期")

    service = VideoOrganizerService(db)
    try:
        body, media_type, filename = await service.export_report(session_id=session_id, format_name=format)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
    }
    return Response(content=body, media_type=media_type, headers=headers)
