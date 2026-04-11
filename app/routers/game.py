"""
BiliMind 知识树学习导航系统

知识预测游戏路由 - 猜关系玩法
"""
import random
from typing import Optional
from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from app.database import get_db
from app.models import GameScore
from app.routers.knowledge import get_graph

router = APIRouter(prefix="/game", tags=["知识游戏"])

# 有效关系类型
VALID_RELATIONS = [
    "prerequisite_of",
    "part_of",
    "related_to",
    "explains",
    "supports",
    "recommends_next",
]

RELATION_LABELS = {
    "prerequisite_of": "前置知识",
    "part_of": "属于/包含",
    "related_to": "相关",
    "explains": "解释说明",
    "supports": "支撑论证",
    "recommends_next": "推荐下一步",
    "无关系": "无关系",
}


class AnswerRequest(BaseModel):
    session_id: str
    node_a_id: int
    node_b_id: int
    answer: str


@router.get("/challenge")
async def get_challenge(session_id: Optional[str] = Query(None, description="会话ID")):
    """随机生成一道知识关系预测题"""
    graph = get_graph()
    edges = list(graph.graph.edges(data=True))

    if not edges:
        raise HTTPException(status_code=404, detail="知识图谱中没有边，无法生成题目")

    # 随机选一条边
    src, tgt, data = random.choice(edges)
    correct_relation = data.get("relation_type", "related_to")

    # 获取节点信息
    src_data = graph.get_node(src) or {}
    tgt_data = graph.get_node(tgt) or {}

    # 构造选项: 正确答案 + "无关系" + 2个干扰项
    distractors = [r for r in VALID_RELATIONS if r != correct_relation]
    random.shuffle(distractors)
    options = [correct_relation, "无关系"] + distractors[:2]
    random.shuffle(options)

    return {
        "node_a": {
            "id": src,
            "name": src_data.get("name", f"Node {src}"),
            "type": src_data.get("node_type", "concept"),
            "definition": src_data.get("definition", ""),
        },
        "node_b": {
            "id": tgt,
            "name": tgt_data.get("name", f"Node {tgt}"),
            "type": tgt_data.get("node_type", "concept"),
            "definition": tgt_data.get("definition", ""),
        },
        "options": options,
        "option_labels": {o: RELATION_LABELS.get(o, o) for o in options},
    }


@router.post("/answer")
async def submit_answer(
    req: AnswerRequest,
    db: AsyncSession = Depends(get_db),
):
    """提交答案并更新分数"""
    graph = get_graph()

    # 查找实际关系
    edge_data = graph.graph.get_edge_data(req.node_a_id, req.node_b_id)
    if edge_data is None:
        # 也检查反向
        edge_data = graph.graph.get_edge_data(req.node_b_id, req.node_a_id)

    correct_answer = edge_data.get("relation_type", "related_to") if edge_data else "无关系"
    is_correct = req.answer == correct_answer

    # 获取节点名称用于解释
    src_data = graph.get_node(req.node_a_id) or {}
    tgt_data = graph.get_node(req.node_b_id) or {}
    src_name = src_data.get("name", "A")
    tgt_name = tgt_data.get("name", "B")

    explanation = (
        f"「{src_name}」与「{tgt_name}」之间的关系是：{RELATION_LABELS.get(correct_answer, correct_answer)}"
    )

    # 更新 GameScore
    result = await db.execute(
        select(GameScore).where(GameScore.session_id == req.session_id)
    )
    score_record = result.scalar_one_or_none()

    if score_record is None:
        score_record = GameScore(
            session_id=req.session_id,
            score=0, total_challenges=0, correct_count=0, streak=0, best_streak=0,
        )
        db.add(score_record)
        await db.flush()

    score_record.total_challenges = (score_record.total_challenges or 0) + 1
    if is_correct:
        score_record.correct_count = (score_record.correct_count or 0) + 1
        score_record.streak = (score_record.streak or 0) + 1
        score_record.score = (score_record.score or 0) + 10 + score_record.streak * 2
        if score_record.streak > (score_record.best_streak or 0):
            score_record.best_streak = score_record.streak
    else:
        score_record.streak = 0

    try:
        await db.commit()
        await db.refresh(score_record)
    except Exception as e:
        logger.error(f"游戏分数保存失败: {e}")
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"保存失败: {e}")

    return {
        "correct": is_correct,
        "correct_answer": correct_answer,
        "correct_answer_label": RELATION_LABELS.get(correct_answer, correct_answer),
        "explanation": explanation,
        "score": score_record.score,
        "streak": score_record.streak,
    }


@router.get("/stats")
async def get_stats(
    session_id: str = Query(..., description="会话ID"),
    db: AsyncSession = Depends(get_db),
):
    """获取用户游戏统计"""
    result = await db.execute(
        select(GameScore).where(GameScore.session_id == session_id)
    )
    record = result.scalar_one_or_none()

    if record is None:
        return {
            "total": 0,
            "correct": 0,
            "streak": 0,
            "best_streak": 0,
            "score": 0,
        }

    return {
        "total": record.total_challenges,
        "correct": record.correct_count,
        "streak": record.streak,
        "best_streak": record.best_streak,
        "score": record.score,
    }
