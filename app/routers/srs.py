"""
BiliMind 知识树学习导航系统

间隔重复路由 - 层级 SRS
"""
from fastapi import APIRouter, Query, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from app.database import get_db
from app.routers.knowledge import get_graph
from app.services.srs import record_review, get_due_reviews, get_stats

router = APIRouter(prefix="/srs", tags=["间隔重复"])


class ReviewRequest(BaseModel):
    session_id: str
    node_id: int
    quality: int  # 0-5


@router.get("/due")
async def due_reviews(
    session_id: str = Query(..., description="会话ID"),
    db: AsyncSession = Depends(get_db),
):
    """获取待复习的知识点列表"""
    items = await get_due_reviews(db, session_id)
    return {"items": items, "count": len(items)}


@router.post("/review")
async def submit_review(
    req: ReviewRequest,
    db: AsyncSession = Depends(get_db),
):
    """提交复习结果，返回更新后的 SRS 状态 + 隐式复习节点"""
    graph = get_graph()
    result = await record_review(
        db, req.session_id, req.node_id, req.quality, graph
    )
    return result


@router.get("/stats")
async def srs_stats(
    session_id: str = Query(..., description="会话ID"),
    db: AsyncSession = Depends(get_db),
):
    """获取 SRS 统计信息"""
    stats = await get_stats(db, session_id)
    return stats
