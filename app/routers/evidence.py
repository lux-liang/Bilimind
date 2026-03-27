"""
知映 ZhiYing — 证据级问答路由

POST /evidence/ask       — 非流式，返回 JSON
POST /evidence/ask/stream — SSE 流式，text chunks + [[EVIDENCE_JSON]]
"""
import json
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
from loguru import logger
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.evidence_qa import ask_with_evidence, ask_with_evidence_stream

router = APIRouter(prefix="/evidence", tags=["证据级问答"])


# ── 请求 / 响应模型 ──────────────────────────────────────────

class EvidenceAskRequest(BaseModel):
    question: str
    session_id: Optional[str] = None


class EvidenceItem(BaseModel):
    ref: int
    video_title: str = ""
    bvid: str = ""
    time: str = ""
    start_time: Optional[int] = None
    end_time: Optional[int] = None
    text: str = ""
    concept: str = ""
    claim: str = ""


class EvidenceAskResponse(BaseModel):
    answer: str
    evidence: list[EvidenceItem] = []
    concept_count: int = 0


# ── 路由 ──────────────────────────────────────────────────────

@router.post("/ask", response_model=EvidenceAskResponse)
async def evidence_ask(request: EvidenceAskRequest, db: AsyncSession = Depends(get_db)):
    """证据级问答（非流式）"""
    if not request.question or not request.question.strip():
        raise HTTPException(status_code=400, detail="问题不能为空")
    try:
        result = await ask_with_evidence(db, request.question.strip(), request.session_id)
        return EvidenceAskResponse(**result)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[EvidenceQA] 问答失败: {e}")
        raise HTTPException(status_code=500, detail=f"证据级问答失败: {str(e)}")


@router.post("/ask/stream")
async def evidence_ask_stream(request: EvidenceAskRequest, db: AsyncSession = Depends(get_db)):
    """证据级问答（SSE 流式）"""
    if not request.question or not request.question.strip():
        raise HTTPException(status_code=400, detail="问题不能为空")
    try:
        generator = await ask_with_evidence_stream(db, request.question.strip(), request.session_id)
        return StreamingResponse(generator, media_type="text/plain; charset=utf-8")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[EvidenceQA] 流式问答失败: {e}")
        raise HTTPException(status_code=500, detail=f"证据级流式问答失败: {str(e)}")
