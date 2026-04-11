"""
知映 ZhiYing — 知识编译引擎

将视频内容编译为 Concept-Claim-Evidence 三级知识结构：
- Concept: 抽象概念（如"梯度下降"）
- Claim: 具体论断（如"梯度下降通过负梯度方向迭代更新参数"）
- Evidence: 锚定到视频时间戳的原始字幕片段
"""
import asyncio
import json
import re
import inspect
from typing import Awaitable, Callable, Optional

from loguru import logger
from openai import AsyncOpenAI
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import (
    Concept, Claim, ConceptRelation, Segment, VideoCache,
)
from app.services.extractor import (
    NOISE_EN_WORDS, NOISE_ZH_WORDS, OVERLY_BROAD,
)


# ==================== LLM 客户端 ====================

_client: Optional[AsyncOpenAI] = None


def _get_client() -> Optional[AsyncOpenAI]:
    global _client
    if _client is None and settings.openai_api_key:
        _client = AsyncOpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
        )
    return _client


def _is_llm_auth_error(err: Exception) -> bool:
    text = str(err).lower()
    return (
        "invalid_api_key" in text
        or "incorrect api key" in text
        or ("error code: 401" in text and "api key" in text)
    )


# ==================== 编译 Prompt ====================

COMPILATION_PROMPT = """你是视频知识编译专家。请将以下视频片段编译为结构化知识。

视频标题：{title}
时间段：{start_time_fmt}-{end_time_fmt}
字幕文本：{text}

请严格输出以下JSON格式（不要输出其他内容）：
{{
  "concepts": [
    {{"name": "概念名", "definition": "一句话定义", "difficulty": 1-5}}
  ],
  "claims": [
    {{
      "concept": "关联概念名",
      "statement": "该片段提出的具体论断/知识点",
      "type": "definition|explanation|example|comparison|warning",
      "confidence": 0.0-1.0
    }}
  ],
  "prerequisites": ["前置概念1", "前置概念2"]
}}

规则：
1. concept 是抽象概念（如"梯度下降"），claim 是具体论断（如"梯度下降通过负梯度方向迭代更新参数"）
2. 每个 claim 必须关联到一个 concept
3. prerequisites 是学习当前概念需要先掌握的概念
4. confidence < 0.3 不要输出
5. 不要抽取过于宽泛的概念（如"学习""内容""视频""方法"等）
6. 概念数量控制在 1-5 个，论断数量控制在 1-8 个"""


# ==================== 噪声过滤 ====================

def _is_noise_concept(name: str) -> bool:
    """判断概念名是否为噪声（复用 extractor 的噪声词表）"""
    lower = name.strip().lower()
    if lower in NOISE_EN_WORDS:
        return True
    if name in NOISE_ZH_WORDS:
        return True
    if lower in OVERLY_BROAD:
        return True
    if re.match(r'^[\d\s.\-]+$', name):
        return True
    if len(name) == 1:
        return True
    if re.match(r'^[a-zA-Z]{1,3}$', name):
        return True
    if re.match(r'^[\W_]+$', name):
        return True
    return False


def _normalize_name(name: str) -> str:
    """归一化概念名"""
    name = name.strip().lower()
    name = re.sub(r"\s+", " ", name)
    name = re.sub(r"[（(].*?[）)]", "", name).strip()
    return name


def _fmt_time(seconds: Optional[float]) -> str:
    """格式化秒为 MM:SS 或 H:MM:SS"""
    if seconds is None:
        return "?:??"
    total = int(seconds)
    m, s = divmod(total, 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


# ==================== 核心：编译单个片段 ====================

async def _compile_segment(
    text: str,
    video_title: str,
    start_time: Optional[float],
    end_time: Optional[float],
) -> dict:
    """
    对单个片段调用 LLM 进行知识编译

    Returns:
        {"concepts": [...], "claims": [...], "prerequisites": [...]}
    """
    client = _get_client()
    if not client:
        logger.warning("LLM 客户端未配置，跳过编译")
        return {"concepts": [], "claims": [], "prerequisites": []}

    # 跳过过短文本
    if not text or len(text.strip()) < 30:
        return {"concepts": [], "claims": [], "prerequisites": []}

    prompt = COMPILATION_PROMPT.format(
        title=video_title,
        start_time_fmt=_fmt_time(start_time),
        end_time_fmt=_fmt_time(end_time),
        text=text[:3000],
    )

    last_error = None
    for attempt in range(2):  # 最多重试 1 次
        try:
            response = await client.chat.completions.create(
                model=settings.llm_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=2000,
                timeout=30,
            )
            raw = response.choices[0].message.content.strip()
            parsed = _parse_compilation_output(raw)
            return parsed
        except Exception as e:
            # 认证错误直接终止，避免误报“编译完成但无知识点”
            if _is_llm_auth_error(e):
                raise RuntimeError(
                    "LLM 鉴权失败（API Key 无效）。请检查 DASHSCOPE_API_KEY / OPENAI_API_KEY。"
                ) from e
            last_error = e
            if attempt == 0:
                logger.warning(f"编译片段失败(尝试{attempt+1})，重试: {e}")
                await asyncio.sleep(1)

    logger.warning(f"编译片段最终失败: {last_error}")
    return {"concepts": [], "claims": [], "prerequisites": []}


def _parse_compilation_output(raw: str) -> dict:
    """解析 LLM 的 JSON 输出"""
    # 尝试从 markdown 代码块提取
    json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if json_match:
        raw = json_match.group(1)

    # 直接找 JSON 对象
    brace_start = raw.find("{")
    brace_end = raw.rfind("}")
    if brace_start != -1 and brace_end != -1:
        raw = raw[brace_start:brace_end + 1]

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Failed to parse compilation output as JSON")
        return {"concepts": [], "claims": [], "prerequisites": []}

    # 验证并过滤 concepts
    concepts = []
    for c in data.get("concepts", []):
        if not isinstance(c, dict):
            continue
        name = (c.get("name") or "").strip()
        if not name or len(name) < 2:
            continue
        if _is_noise_concept(name):
            continue
        difficulty = int(c.get("difficulty", 1))
        difficulty = max(1, min(5, difficulty))
        concepts.append({
            "name": name,
            "definition": (c.get("definition") or "").strip(),
            "difficulty": difficulty,
        })

    # 验证 claims
    valid_types = {"definition", "explanation", "example", "comparison", "warning"}
    claims = []
    for cl in data.get("claims", []):
        if not isinstance(cl, dict):
            continue
        concept_name = (cl.get("concept") or "").strip()
        statement = (cl.get("statement") or "").strip()
        if not concept_name or not statement:
            continue
        confidence = float(cl.get("confidence", 0.5))
        if confidence < 0.3:
            continue
        claim_type = cl.get("type", "explanation")
        if claim_type not in valid_types:
            claim_type = "explanation"
        claims.append({
            "concept": concept_name,
            "statement": statement,
            "type": claim_type,
            "confidence": confidence,
        })

    # 验证 prerequisites
    prerequisites = []
    for p in data.get("prerequisites", []):
        if isinstance(p, str) and len(p.strip()) >= 2:
            p_name = p.strip()
            if not _is_noise_concept(p_name):
                prerequisites.append(p_name)

    return {
        "concepts": concepts,
        "claims": claims,
        "prerequisites": prerequisites,
    }


# ==================== 跨片段合并 ====================

def _merge_concepts(all_segment_results: list[dict]) -> dict:
    """
    合并多个片段的编译结果，按 normalized_name 去重概念

    Returns:
        {
            "concepts": {normalized_name: {name, definition, difficulty, source_count, claims: [...]}},
            "prerequisites": [(source_norm, target_norm)],
        }
    """
    concept_map: dict[str, dict] = {}  # normalized_name -> concept info
    all_prerequisites: list[tuple[str, str]] = []

    for seg_result in all_segment_results:
        seg_concepts = seg_result.get("concepts", [])
        seg_claims = seg_result.get("claims", [])
        seg_prereqs = seg_result.get("prerequisites", [])
        seg_start = seg_result.get("start_time")
        seg_end = seg_result.get("end_time")
        seg_text = seg_result.get("raw_text", "")

        # 建立本片段内 concept name -> normalized 映射
        local_name_map: dict[str, str] = {}
        for c in seg_concepts:
            normalized = _normalize_name(c["name"])
            local_name_map[c["name"]] = normalized

            if normalized in concept_map:
                existing = concept_map[normalized]
                existing["source_count"] += 1
                existing["difficulty"] = max(existing["difficulty"], c.get("difficulty", 1))
                if c.get("definition") and not existing.get("definition"):
                    existing["definition"] = c["definition"]
            else:
                concept_map[normalized] = {
                    "name": c["name"],
                    "normalized_name": normalized,
                    "definition": c.get("definition", ""),
                    "difficulty": c.get("difficulty", 1),
                    "source_count": 1,
                    "claims": [],
                }

        # 挂载 claims 到对应 concept
        for cl in seg_claims:
            concept_name = cl["concept"]
            normalized = local_name_map.get(concept_name)
            if not normalized:
                # 尝试模糊匹配
                normalized = _normalize_name(concept_name)
            if normalized in concept_map:
                concept_map[normalized]["claims"].append({
                    "statement": cl["statement"],
                    "type": cl["type"],
                    "confidence": cl["confidence"],
                    "start_time": seg_start,
                    "end_time": seg_end,
                    "raw_text": seg_text,
                })

        # 收集前置关系
        # prerequisites 是当前片段概念的前置，建立 prerequisite -> concept 关系
        for prereq_name in seg_prereqs:
            prereq_norm = _normalize_name(prereq_name)
            # prerequisite_of 关系：prereq 是 concept 的前置
            for c in seg_concepts:
                c_norm = _normalize_name(c["name"])
                if prereq_norm != c_norm:
                    all_prerequisites.append((prereq_norm, c_norm))

            # 如果 prerequisite 自身不在 concept_map 中，也创建一个轻量概念
            if prereq_norm not in concept_map:
                concept_map[prereq_norm] = {
                    "name": prereq_name,
                    "normalized_name": prereq_norm,
                    "definition": "",
                    "difficulty": 1,
                    "source_count": 0,
                    "claims": [],
                }

    # 去重 prerequisites
    unique_prereqs = list(set(all_prerequisites))

    return {
        "concepts": concept_map,
        "prerequisites": unique_prereqs,
    }


# ==================== 知识密度 ====================

def _calculate_density(
    segments: list[dict],
    claims: list[dict],
) -> list[dict]:
    """
    计算每个片段的知识密度

    Args:
        segments: [{"start_time", "end_time", ...}]
        claims: [{"start_time", "end_time", ...}]

    Returns:
        segments with added "knowledge_density" and "is_peak" fields
    """
    if not segments:
        return segments

    for seg in segments:
        seg_start = seg.get("start_time") or 0
        seg_end = seg.get("end_time") or seg_start
        duration = max(seg_end - seg_start, 1)

        # 统计落在此片段时间范围内的 claim 数量
        claim_count = 0
        seg_concept_names = set()
        for cl in claims:
            cl_start = cl.get("start_time")
            cl_end = cl.get("end_time")
            if cl_start is None or cl_end is None:
                continue
            # claim 的时间范围与 segment 有重叠
            if cl_start < seg_end and cl_end > seg_start:
                claim_count += 1
                if cl.get("concept_normalized"):
                    seg_concept_names.add(cl["concept_normalized"])

        density = claim_count / duration
        seg["knowledge_density"] = round(density, 4)
        seg["claim_count"] = claim_count
        seg["concept_names"] = list(seg_concept_names)

    # 计算平均密度，标记峰值
    densities = [s["knowledge_density"] for s in segments]
    avg_density = sum(densities) / len(densities) if densities else 0

    for seg in segments:
        seg["is_peak"] = seg["knowledge_density"] > avg_density * 1.5

    return segments


# ==================== 主入口：编译视频 ====================

async def compile_video(
    db: AsyncSession,
    bvid: str,
    session_id: str,
    content_fetcher,
    progress_callback: Optional[Callable[[float, str], Awaitable[None] | None]] = None,
) -> dict:
    """
    编译视频内容为 Concept-Claim-Evidence 知识结构

    Args:
        db: 数据库会话
        bvid: 视频 BV 号
        session_id: 用户会话 ID
        content_fetcher: ContentFetcher 实例

    Returns:
        {
            "bvid": str,
            "concept_count": int,
            "claim_count": int,
            "peak_count": int,
            "segment_count": int,
        }
    """
    logger.info(f"[{bvid}] 开始知识编译...")

    async def _report(progress: float, message: str) -> None:
        if not progress_callback:
            return
        ret = progress_callback(max(0.0, min(1.0, progress)), message)
        if inspect.isawaitable(ret):
            await ret

    # 获取视频信息
    result = await db.execute(
        select(VideoCache).where(VideoCache.bvid == bvid)
    )
    video_cache = result.scalar_one_or_none()
    video_title = video_cache.title if video_cache else "未知标题"
    video_duration = video_cache.duration if video_cache else None

    # Step 1: 获取片段
    await _report(0.22, "正在读取字幕/音频...")
    segments_data = await content_fetcher.fetch_segments(bvid)
    if not segments_data:
        logger.warning(f"[{bvid}] 无法获取视频片段")
        await _report(0.95, "未获取到可用片段")
        return {
            "bvid": bvid,
            "concept_count": 0,
            "claim_count": 0,
            "peak_count": 0,
            "segment_count": 0,
        }

    logger.info(f"[{bvid}] 获取到 {len(segments_data)} 个片段")

    # 清除旧的编译数据（如果存在）
    existing_concepts = await db.execute(
        select(Concept).where(
            Concept.session_id == session_id,
        )
    )
    existing_concept_list = existing_concepts.scalars().all()
    # 检查是否有与此视频关联的 claim
    video_claim_concept_ids = set()
    for concept in existing_concept_list:
        claim_result = await db.execute(
            select(Claim.id).where(
                Claim.concept_id == concept.id,
                Claim.video_bvid == bvid,
            )
        )
        if claim_result.scalars().first() is not None:
            video_claim_concept_ids.add(concept.id)

    # 删除此视频的旧 claims
    if video_claim_concept_ids:
        from sqlalchemy import delete
        await db.execute(
            delete(Claim).where(
                Claim.video_bvid == bvid,
                Claim.session_id == session_id,
            )
        )
        # 删除没有其他 claim 的空概念
        for cid in video_claim_concept_ids:
            remaining = await db.scalar(
                select(func.count()).select_from(Claim).where(Claim.concept_id == cid)
            )
            if remaining == 0:
                await db.execute(
                    delete(Concept).where(Concept.id == cid)
                )
        # 删除旧的 ConceptRelation
        await db.execute(
            delete(ConceptRelation).where(
                ConceptRelation.session_id == session_id,
            )
        )

    # 删除旧 Segment 记录
    from sqlalchemy import delete as sql_delete
    await db.execute(
        sql_delete(Segment).where(
            Segment.video_bvid == bvid,
            Segment.session_id == session_id,
        )
    )
    await db.flush()

    # 写入新 Segment 记录
    segment_records = []
    for seg in segments_data:
        record = Segment(
            video_bvid=bvid,
            segment_index=seg["segment_index"],
            start_time=seg.get("start_time"),
            end_time=seg.get("end_time"),
            raw_text=seg["raw_text"],
            cleaned_text=seg["raw_text"],
            source_type=seg.get("source_type", "unknown"),
            confidence=seg.get("confidence", 0.5),
            extraction_status="pending",
            session_id=session_id,
        )
        db.add(record)
        segment_records.append(record)
    await db.flush()
    # 关键：不要把后续 LLM 调用放在同一个未提交事务里，否则会长时间占用 SQLite 写锁。
    # 这里先提交“旧数据删除 + 新片段写入”，释放写锁，降低并发请求被 lock 的概率。
    await db.commit()

    # 保护：若本次仅拿到 basic_info 兜底片段，则不进行 LLM 编译，避免凭标题/简介臆测错误知识。
    non_basic_segments = [s for s in segment_records if (s.source_type or "").lower() != "basic"]
    if not non_basic_segments:
        for seg in segment_records:
            seg.extraction_status = "done"
            seg.knowledge_density = 0.0
            seg.is_peak = False
        await db.commit()
        await _report(0.95, "字幕/ASR不可用，仅有基础信息，已跳过知识编译")
        logger.warning(f"[{bvid}] 仅基础信息片段，跳过知识编译")
        return {
            "bvid": bvid,
            "concept_count": 0,
            "claim_count": 0,
            "peak_count": 0,
            "segment_count": len(segment_records),
        }

    # Step 2: 逐片段编译
    await _report(0.28, f"开始编译 {len(segment_records)} 个片段...")
    all_segment_results = []
    total_segments = len(non_basic_segments)
    for i, seg_rec in enumerate(non_basic_segments):
        seg_result = await _compile_segment(
            text=seg_rec.raw_text,
            video_title=video_title,
            start_time=seg_rec.start_time,
            end_time=seg_rec.end_time,
        )
        # 附加片段元信息
        seg_result["start_time"] = seg_rec.start_time
        seg_result["end_time"] = seg_rec.end_time
        seg_result["raw_text"] = seg_rec.raw_text
        seg_result["segment_id"] = seg_rec.id
        all_segment_results.append(seg_result)

        seg_rec.extraction_status = "done"
        logger.debug(
            f"[{bvid}] 片段 {seg_rec.segment_index}: "
            f"{len(seg_result.get('concepts', []))} 概念, "
            f"{len(seg_result.get('claims', []))} 论断"
        )
        await _report(0.28 + 0.52 * ((i + 1) / max(total_segments, 1)), f"正在编译片段 {i + 1}/{total_segments}...")

    # Step 3: 跨片段合并
    await _report(0.84, "正在合并知识结构...")
    merged = _merge_concepts(all_segment_results)
    concept_map = merged["concepts"]
    prerequisite_pairs = merged["prerequisites"]

    logger.info(
        f"[{bvid}] 合并后: {len(concept_map)} 概念, "
        f"{sum(len(c['claims']) for c in concept_map.values())} 论断, "
        f"{len(prerequisite_pairs)} 前置关系"
    )

    # Step 4: 写入 Concept 和 Claim 表
    await _report(0.9, "正在写入知识点与论断...")
    norm_to_concept_id: dict[str, int] = {}
    total_claims = 0

    for norm_name, cdata in concept_map.items():
        # 查找是否已存在同名概念（跨视频复用）
        existing = await db.execute(
            select(Concept).where(
                Concept.normalized_name == norm_name,
                Concept.session_id == session_id,
            )
        )
        concept_row = existing.scalar_one_or_none()

        if concept_row:
            # 更新已有概念
            concept_row.source_count += cdata["source_count"]
            concept_row.video_count = (concept_row.video_count or 1) + 1
            concept_row.difficulty = max(concept_row.difficulty or 1, cdata["difficulty"])
            if cdata["definition"] and not concept_row.definition:
                concept_row.definition = cdata["definition"]
        else:
            concept_row = Concept(
                session_id=session_id,
                name=cdata["name"],
                normalized_name=norm_name,
                definition=cdata["definition"],
                difficulty=cdata["difficulty"],
                source_count=cdata["source_count"],
                video_count=1,
            )
            db.add(concept_row)
            await db.flush()

        norm_to_concept_id[norm_name] = concept_row.id

        # 写入 Claim
        for cl in cdata["claims"]:
            # 查找对应的 segment_id
            seg_id = None
            for seg_rec in segment_records:
                if seg_rec.start_time == cl.get("start_time") and seg_rec.end_time == cl.get("end_time"):
                    seg_id = seg_rec.id
                    break

            claim_row = Claim(
                session_id=session_id,
                concept_id=concept_row.id,
                statement=cl["statement"],
                claim_type=cl["type"],
                confidence=cl["confidence"],
                segment_id=seg_id,
                video_bvid=bvid,
                start_time=cl.get("start_time"),
                end_time=cl.get("end_time"),
                raw_text=cl.get("raw_text", ""),
            )
            db.add(claim_row)
            total_claims += 1

    await db.flush()

    # Step 5: 写入 ConceptRelation（前置关系）
    await _report(0.94, "正在构建前置关系...")
    for src_norm, tgt_norm in prerequisite_pairs:
        src_id = norm_to_concept_id.get(src_norm)
        tgt_id = norm_to_concept_id.get(tgt_norm)
        if src_id and tgt_id and src_id != tgt_id:
            rel = ConceptRelation(
                session_id=session_id,
                source_concept_id=src_id,
                target_concept_id=tgt_id,
                relation_type="prerequisite_of",
                confidence=0.6,
            )
            db.add(rel)

    # Step 6: 计算知识密度并更新 Segment
    await _report(0.97, "正在计算知识密度...")
    # 收集所有 claims 的时间信息
    all_claims_for_density = []
    for norm_name, cdata in concept_map.items():
        for cl in cdata["claims"]:
            all_claims_for_density.append({
                "start_time": cl.get("start_time"),
                "end_time": cl.get("end_time"),
                "concept_normalized": norm_name,
            })

    seg_density_data = [
        {
            "segment_id": sr.id,
            "start_time": sr.start_time,
            "end_time": sr.end_time,
        }
        for sr in segment_records
    ]
    seg_density_data = _calculate_density(seg_density_data, all_claims_for_density)

    peak_count = 0
    for sd in seg_density_data:
        # 更新 Segment 表
        for sr in segment_records:
            if sr.id == sd["segment_id"]:
                sr.knowledge_density = sd["knowledge_density"]
                sr.is_peak = sd["is_peak"]
                if sd["is_peak"]:
                    peak_count += 1
                break

    await db.commit()
    await _report(0.99, "正在完成收尾...")

    logger.info(
        f"[{bvid}] 知识编译完成: "
        f"{len(concept_map)} 概念, {total_claims} 论断, "
        f"{peak_count} 峰值片段"
    )

    return {
        "bvid": bvid,
        "concept_count": len(concept_map),
        "claim_count": total_claims,
        "peak_count": peak_count,
        "segment_count": len(segment_records),
    }
