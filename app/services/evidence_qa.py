"""
知映 ZhiYing — 证据级问答服务

AI 回答时必须引用具体的 Claim + 视频时间戳。
不是泛泛总结，而是精确到"答案在视频A的4:32-5:18"。
"""
import re
import json
from typing import List, Optional, Dict, Any

from loguru import logger
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession
from openai import OpenAI, AsyncOpenAI

from app.config import settings
from app.models import Concept, Claim, Segment, VideoCache, _fmt_time
from app.services.rag import RAGService


# ── 中文停用词（用于概念提取过滤） ──────────────────────────────
_STOPWORDS = {
    "什么", "怎么", "如何", "是否", "可以", "哪个", "哪些", "请问", "一下",
    "为什么", "有没有", "能不能", "能否", "是不是", "是什么", "多少", "哪里",
    "讲讲", "介绍", "总结", "概括", "分析", "解释", "说明", "评价", "区别",
    "内容", "视频", "知道", "告诉", "关于", "以及", "还有", "这个", "那个",
    "就是", "其实", "但是", "而且", "然后", "或者", "因为", "所以", "如果",
    "虽然", "不过", "这些", "那些", "他们", "我们", "你们", "自己", "什么样",
    "怎样", "一些", "许多", "非常", "比较", "特别", "应该", "需要", "必须",
}

# ── 证据级 System Prompt ────────────────────────────────────
_EVIDENCE_SYSTEM_PROMPT = """你是知映知识助手。请基于以下视频证据回答用户问题。

重要规则：
1. 每个论点必须标注来源编号，如 [1] [2]
2. 只引用证据中明确提到的信息，不要编造
3. 如果证据不足以回答，坦诚说明
4. 回答要自然、有条理

视频证据：
{evidence_context}

用户问题：{question}"""


# =====================================================================
# 辅助函数
# =====================================================================

def _extract_question_concepts(question: str) -> List[str]:
    """从问题中提取可能的概念名称。

    策略：中文 2+ 字词 + 英文 2+ 字母词，过滤停用词。
    """
    concepts: List[str] = []
    # 中文词
    for w in re.findall(r"[\u4e00-\u9fff]{2,}", question):
        if w not in _STOPWORDS and w not in concepts:
            concepts.append(w)
    # 英文/数字词
    for w in re.findall(r"[A-Za-z0-9]{2,}", question):
        if w.lower() not in concepts:
            concepts.append(w)
    return concepts


def _build_evidence_context(
    claims: List[Dict[str, Any]],
    rag_docs: List[Any],
) -> tuple[str, List[Dict[str, Any]]]:
    """合并 Claim 证据 + 向量检索结果，生成带编号的上下文。

    Returns:
        (evidence_context_string, evidence_items_list)
    """
    lines: List[str] = []
    evidence_items: List[Dict[str, Any]] = []
    ref = 1

    # ── Claims 优先 ──────────────────────────────────────────
    for c in claims:
        time_label = ""
        start_time = c.get("start_time")
        end_time = c.get("end_time")
        if start_time is not None and end_time is not None:
            time_label = f"{_fmt_time(start_time)}-{_fmt_time(end_time)}"
        elif start_time is not None:
            time_label = _fmt_time(start_time)

        video_title = c.get("video_title", "")
        header = f"[{video_title}"
        if time_label:
            header += f" \u00b7 {time_label}"
        header += "]"

        raw_text = (c.get("raw_text") or c.get("statement") or "").strip()
        line = f"[{ref}] {header} \"{raw_text}\""
        lines.append(line)

        evidence_items.append({
            "ref": ref,
            "video_title": video_title,
            "bvid": c.get("bvid", ""),
            "time": time_label,
            "start_time": int(start_time) if start_time is not None else None,
            "end_time": int(end_time) if end_time is not None else None,
            "text": raw_text,
            "concept": c.get("concept_name", ""),
            "claim": c.get("statement", ""),
        })
        ref += 1

    # ── RAG 补充（去重已有 bvid+时间段） ───────────────────────
    existing_keys = set()
    for ei in evidence_items:
        existing_keys.add((ei["bvid"], ei.get("start_time")))

    for doc in rag_docs:
        meta = doc.metadata or {}
        bvid = meta.get("bvid", "")
        title = meta.get("title", "")
        content = (doc.page_content or "").strip()
        if not content:
            continue
        # 简单去重
        if (bvid, None) in existing_keys:
            continue

        line = f"[{ref}] [{title}] \"{content[:300]}\""
        lines.append(line)

        evidence_items.append({
            "ref": ref,
            "video_title": title,
            "bvid": bvid,
            "time": "",
            "start_time": None,
            "end_time": None,
            "text": content[:300],
            "concept": "",
            "claim": "",
        })
        ref += 1

    context = "\n\n".join(lines) if lines else "(未找到相关证据)"
    return context, evidence_items


# =====================================================================
# 数据库检索
# =====================================================================

async def _match_concepts(
    db: AsyncSession,
    keywords: List[str],
    session_id: Optional[str] = None,
) -> List[Concept]:
    """根据关键词模糊匹配 Concept 表。"""
    if not keywords:
        return []

    like_conds = []
    for kw in keywords:
        pattern = f"%{kw}%"
        like_conds.append(Concept.normalized_name.ilike(pattern))
        like_conds.append(Concept.name.ilike(pattern))

    stmt = select(Concept).where(or_(*like_conds))
    if session_id:
        stmt = stmt.where(Concept.session_id == session_id)
    stmt = stmt.limit(20)

    result = await db.execute(stmt)
    return list(result.scalars().all())


async def _get_claims_for_concepts(
    db: AsyncSession,
    concept_ids: List[int],
    session_id: Optional[str] = None,
    bvid: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """获取概念关联的所有 Claim，附带视频标题。"""
    if not concept_ids:
        return []

    stmt = (
        select(
            Claim,
            Concept.name.label("concept_name"),
            VideoCache.title.label("video_title"),
        )
        .join(Concept, Concept.id == Claim.concept_id)
        .outerjoin(VideoCache, VideoCache.bvid == Claim.video_bvid)
        .where(Claim.concept_id.in_(concept_ids))
    )
    if session_id:
        stmt = stmt.where(Claim.session_id == session_id)
    if bvid:
        stmt = stmt.where(Claim.video_bvid == bvid)
    stmt = stmt.order_by(Claim.confidence.desc()).limit(30)

    result = await db.execute(stmt)
    rows = result.fetchall()

    claims = []
    for claim, concept_name, video_title in rows:
        claims.append({
            "claim_id": claim.id,
            "concept_name": concept_name or "",
            "statement": claim.statement or "",
            "claim_type": claim.claim_type or "explanation",
            "confidence": claim.confidence,
            "bvid": claim.video_bvid or "",
            "video_title": video_title or "",
            "start_time": claim.start_time,
            "end_time": claim.end_time,
            "raw_text": claim.raw_text or "",
        })
    return claims


async def _get_fallback_claims(
    db: AsyncSession,
    session_id: Optional[str] = None,
    bvid: Optional[str] = None,
    limit: int = 20,
) -> List[Dict[str, Any]]:
    """当关键词召回失败时，回退到高置信度 Claim 作为证据。"""
    stmt = (
        select(
            Claim,
            Concept.name.label("concept_name"),
            VideoCache.title.label("video_title"),
        )
        .join(Concept, Concept.id == Claim.concept_id)
        .outerjoin(VideoCache, VideoCache.bvid == Claim.video_bvid)
    )
    if session_id:
        stmt = stmt.where(Claim.session_id == session_id)
    if bvid:
        stmt = stmt.where(Claim.video_bvid == bvid)

    stmt = stmt.order_by(Claim.confidence.desc(), Claim.id.desc()).limit(limit)
    result = await db.execute(stmt)
    rows = result.fetchall()

    claims: List[Dict[str, Any]] = []
    for claim, concept_name, video_title in rows:
        claims.append({
            "claim_id": claim.id,
            "concept_name": concept_name or "",
            "statement": claim.statement or "",
            "claim_type": claim.claim_type or "explanation",
            "confidence": claim.confidence,
            "bvid": claim.video_bvid or "",
            "video_title": video_title or "",
            "start_time": claim.start_time,
            "end_time": claim.end_time,
            "raw_text": claim.raw_text or "",
        })
    return claims


# =====================================================================
# 主入口
# =====================================================================

def _get_llm_client() -> OpenAI:
    return OpenAI(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
    )


def _get_async_llm_client() -> AsyncOpenAI:
    return AsyncOpenAI(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
    )


async def _retrieve_evidence(
    db: AsyncSession,
    question: str,
    session_id: Optional[str] = None,
    bvid: Optional[str] = None,
) -> tuple[str, List[Dict[str, Any]], int]:
    """检索证据：概念匹配 + Claim + RAG 向量补充。

    Returns:
        (evidence_context, evidence_items, concept_count)
    """
    # Step 1: 提取概念关键词
    keywords = _extract_question_concepts(question)
    logger.info(f"[EvidenceQA] 提取关键词: {keywords}")

    # Step 2: 模糊匹配 Concept
    concepts = await _match_concepts(db, keywords, session_id)
    concept_ids = [c.id for c in concepts]
    concept_count = len(concepts)
    logger.info(f"[EvidenceQA] 匹配概念: {[c.name for c in concepts]}")

    # Step 3: 获取关联 Claim（带时间信息）
    claims = await _get_claims_for_concepts(db, concept_ids, session_id, bvid)
    if not claims:
        # 泛问（如“这个视频核心观点是什么”）常无关键词命中，回退到高置信度论断。
        claims = await _get_fallback_claims(db, session_id, bvid, limit=20)
    logger.info(f"[EvidenceQA] 获取 Claims: {len(claims)} 条")

    # Step 4: RAG 向量检索补充
    rag_docs = []
    try:
        rag = RAGService()
        bvid_filter = [bvid] if bvid else None
        rag_docs = rag.search(question, k=3, bvids=bvid_filter, session_id=session_id)
        logger.info(f"[EvidenceQA] RAG 召回: {len(rag_docs)} 条")
    except Exception as e:
        logger.warning(f"[EvidenceQA] RAG 检索失败: {e}")

    # Step 5: 合并构建证据上下文
    evidence_context, evidence_items = _build_evidence_context(claims, rag_docs)

    return evidence_context, evidence_items, concept_count


async def ask_with_evidence(
    db: AsyncSession,
    question: str,
    session_id: Optional[str] = None,
    bvid: Optional[str] = None,
) -> Dict[str, Any]:
    """证据级问答 — 非流式版本。

    Returns:
        {"answer": str, "evidence": [EvidenceItem], "concept_count": int}
    """
    # 检索证据
    evidence_context, evidence_items, concept_count = await _retrieve_evidence(
        db, question, session_id, bvid
    )

    # 构建 LLM 消息
    system_content = _EVIDENCE_SYSTEM_PROMPT.format(
        evidence_context=evidence_context,
        question=question,
    )
    messages = [
        {"role": "system", "content": system_content},
        {"role": "user", "content": question},
    ]

    # 调用 LLM
    client = _get_llm_client()
    response = client.chat.completions.create(
        model=settings.llm_model,
        messages=messages,
        temperature=0.5,
    )
    answer = response.choices[0].message.content or ""

    return {
        "answer": answer,
        "evidence": evidence_items,
        "concept_count": concept_count,
    }


async def ask_with_evidence_stream(
    db: AsyncSession,
    question: str,
    session_id: Optional[str] = None,
    bvid: Optional[str] = None,
):
    """证据级问答 — SSE 流式版本。

    Yields:
        文本 chunk，最后附加 [[EVIDENCE_JSON]]<json>
    """
    # 检索证据（在流式开始前完成）
    evidence_context, evidence_items, concept_count = await _retrieve_evidence(
        db, question, session_id, bvid
    )

    # 构建 LLM 消息
    system_content = _EVIDENCE_SYSTEM_PROMPT.format(
        evidence_context=evidence_context,
        question=question,
    )
    messages = [
        {"role": "system", "content": system_content},
        {"role": "user", "content": question},
    ]

    # 返回同步生成器（与 chat.py 保持一致）
    client = _get_llm_client()

    def generate():
        stream = client.chat.completions.create(
            model=settings.llm_model,
            messages=messages,
            temperature=0.5,
            stream=True,
        )
        for chunk in stream:
            delta = chunk.choices[0].delta
            if delta and delta.content:
                yield delta.content

        # 追加证据 JSON
        evidence_payload = {
            "evidence": evidence_items,
            "concept_count": concept_count,
        }
        yield f"\n[[EVIDENCE_JSON]]{json.dumps(evidence_payload, ensure_ascii=False)}"

    return generate()
