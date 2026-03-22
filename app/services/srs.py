"""
BiliMind 层级间隔重复服务

基于 SM-2 算法变体，增加图谱隐式复习传播：
- 显式复习：用户直接标记某知识点
- 隐式复习：通过 prerequisite_of 关系自动传播到前置知识
"""
from datetime import datetime, timedelta
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from app.models import SRSRecord, KnowledgeNode
from app.services.graph_store import GraphStore


async def record_review(
    db: AsyncSession,
    session_id: str,
    node_id: int,
    quality: int,
    graph_store: GraphStore,
) -> dict:
    """
    SM-2 显式复习 + 隐式传播

    quality: 0-5 (0=forgot, 5=perfect)
    Returns: updated record info + list of implicitly reviewed nodes
    """
    quality = max(0, min(5, quality))

    # Get or create SRS record
    result = await db.execute(
        select(SRSRecord).where(
            SRSRecord.session_id == session_id,
            SRSRecord.node_id == node_id,
        )
    )
    record = result.scalar_one_or_none()

    if record is None:
        record = SRSRecord(
            session_id=session_id,
            node_id=node_id,
            easiness_factor=2.5,
            interval_days=1.0,
            repetitions=0,
            implicit_review=False,
        )
        db.add(record)

    # SM-2 algorithm
    ef = record.easiness_factor
    ef_new = ef + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
    ef_new = max(1.3, ef_new)

    if quality >= 3:
        if record.repetitions == 0:
            interval = 1.0
        elif record.repetitions == 1:
            interval = 6.0
        else:
            interval = record.interval_days * ef_new
        record.repetitions += 1
    else:
        interval = 1.0
        record.repetitions = 0

    record.easiness_factor = ef_new
    record.interval_days = interval
    record.next_review_date = datetime.utcnow() + timedelta(days=interval)
    record.last_review_date = datetime.utcnow()
    record.implicit_review = False

    await db.flush()

    # Propagate implicit reviews
    implicit_nodes = []
    await _propagate_implicit(
        db, session_id, node_id, graph_store,
        base_interval=interval,
        depth=0, max_depth=3,
        visited=set(),
        implicit_nodes=implicit_nodes,
    )

    await db.commit()

    return {
        "node_id": node_id,
        "easiness_factor": round(record.easiness_factor, 2),
        "interval_days": round(record.interval_days, 1),
        "repetitions": record.repetitions,
        "next_review_date": record.next_review_date.isoformat() if record.next_review_date else None,
        "implicit_reviewed": implicit_nodes,
    }


async def _propagate_implicit(
    db: AsyncSession,
    session_id: str,
    node_id: int,
    graph_store: GraphStore,
    base_interval: float,
    depth: int,
    max_depth: int,
    visited: set,
    implicit_nodes: list,
):
    """Recursive prerequisite propagation with 0.5x interval growth per level."""
    if depth >= max_depth:
        return

    prerequisites = graph_store.get_prerequisites(node_id)
    for prereq in prerequisites:
        prereq_id = prereq.get("id") or prereq.get("node_id")
        if prereq_id is None or prereq_id in visited:
            continue
        visited.add(prereq_id)

        # Get or create record for prerequisite
        result = await db.execute(
            select(SRSRecord).where(
                SRSRecord.session_id == session_id,
                SRSRecord.node_id == prereq_id,
            )
        )
        rec = result.scalar_one_or_none()

        # Implicit interval grows at 0.5x per depth level
        implicit_interval = base_interval * (0.5 ** (depth + 1))

        if rec is None:
            rec = SRSRecord(
                session_id=session_id,
                node_id=prereq_id,
                easiness_factor=2.5,
                interval_days=implicit_interval,
                repetitions=1,
                next_review_date=datetime.utcnow() + timedelta(days=implicit_interval),
                last_review_date=datetime.utcnow(),
                implicit_review=True,
            )
            db.add(rec)
        else:
            # Only update if implicit review would push the date further
            new_next = datetime.utcnow() + timedelta(days=max(rec.interval_days, implicit_interval))
            if rec.next_review_date is None or new_next > rec.next_review_date:
                rec.interval_days = max(rec.interval_days, implicit_interval)
                rec.next_review_date = new_next
                rec.last_review_date = datetime.utcnow()
                rec.implicit_review = True

        # Get node name for response
        node_data = graph_store.get_node(prereq_id)
        name = node_data.get("name", f"Node {prereq_id}") if node_data else f"Node {prereq_id}"
        implicit_nodes.append({"node_id": prereq_id, "name": name, "depth": depth + 1})

        # Recurse
        await _propagate_implicit(
            db, session_id, prereq_id, graph_store,
            base_interval=base_interval,
            depth=depth + 1,
            max_depth=max_depth,
            visited=visited,
            implicit_nodes=implicit_nodes,
        )


async def get_due_reviews(db: AsyncSession, session_id: str) -> list[dict]:
    """Query SRSRecord where next_review_date <= now, return node details."""
    now = datetime.utcnow()
    result = await db.execute(
        select(SRSRecord).where(
            SRSRecord.session_id == session_id,
            SRSRecord.next_review_date <= now,
        ).order_by(SRSRecord.next_review_date.asc())
    )
    records = result.scalars().all()

    dues = []
    for rec in records:
        # Get node info from DB
        node_result = await db.execute(
            select(KnowledgeNode).where(KnowledgeNode.id == rec.node_id)
        )
        node = node_result.scalar_one_or_none()

        dues.append({
            "node_id": rec.node_id,
            "name": node.name if node else f"Node {rec.node_id}",
            "definition": node.definition if node else None,
            "node_type": node.node_type if node else "concept",
            "easiness_factor": round(rec.easiness_factor, 2),
            "interval_days": round(rec.interval_days, 1),
            "repetitions": rec.repetitions,
            "next_review_date": rec.next_review_date.isoformat() if rec.next_review_date else None,
            "implicit_review": rec.implicit_review,
        })

    return dues


async def get_stats(db: AsyncSession, session_id: str) -> dict:
    """Count total, due, mastered (interval > 21 days)."""
    now = datetime.utcnow()

    # Total tracked
    total_result = await db.execute(
        select(func.count()).select_from(SRSRecord).where(
            SRSRecord.session_id == session_id,
        )
    )
    total = total_result.scalar() or 0

    # Due today
    due_result = await db.execute(
        select(func.count()).select_from(SRSRecord).where(
            SRSRecord.session_id == session_id,
            SRSRecord.next_review_date <= now,
        )
    )
    due = due_result.scalar() or 0

    # Mastered (interval > 21 days)
    mastered_result = await db.execute(
        select(func.count()).select_from(SRSRecord).where(
            SRSRecord.session_id == session_id,
            SRSRecord.interval_days > 21,
        )
    )
    mastered = mastered_result.scalar() or 0

    # Average retention (proportion not due)
    avg_retention = round((total - due) / total, 2) if total > 0 else 0.0

    return {
        "total_tracked": total,
        "due_today": due,
        "mastered": mastered,
        "avg_retention": avg_retention,
    }
