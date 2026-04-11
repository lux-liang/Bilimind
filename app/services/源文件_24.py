"""
Evidence relevance ranker.

将现有规则分和轻量二分类模型结合，用于知识节点 -> 视频片段证据排序。
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from functools import lru_cache
from pathlib import Path
from typing import Optional, Any

from app.config import settings
from app.models import KnowledgeNode, NodeSegmentLink, Segment, VideoCache
from app.services.lightweight_models import HashedBinaryLogisticModel

HIGH_CONFIDENCE_THRESHOLD = 0.78
MEDIUM_CONFIDENCE_THRESHOLD = 0.60


@dataclass
class EvidenceInference:
    relevance_score: float
    model_score: float
    rule_score: float
    is_relevant: bool
    confidence_level: str
    used_model: bool


def _normalize_text(value: Optional[str]) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def _tokenize(value: str) -> list[str]:
    tokens = re.findall(r"[a-zA-Z0-9\u4e00-\u9fff]+", value.lower())
    return [token for token in tokens if len(token) > 1]


def _jaccard(left: list[str], right: list[str]) -> float:
    a, b = set(left), set(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _node_name_tokens(node: KnowledgeNode) -> list[str]:
    return _tokenize(" ".join([node.name, *(node.aliases or [])]))


def _node_context_tokens(node: KnowledgeNode) -> list[str]:
    return _tokenize(" ".join([node.name, node.definition or "", *(node.aliases or [])]))


def _title_tokens(video: Optional[VideoCache]) -> list[str]:
    return _tokenize(video.title if video else "")


def _has_name_or_alias_match(node: KnowledgeNode, haystack: str) -> bool:
    name_norm = _normalize_text(node.name)
    if name_norm and name_norm in haystack:
        return True
    return any(
        alias_norm and alias_norm in haystack
        for alias_norm in (_normalize_text(alias) for alias in (node.aliases or []))
    )


def _is_generic_node(node: KnowledgeNode) -> bool:
    generic_names = {"学习", "知识", "方法", "技术", "系统", "工具", "应用", "内容", "视频"}
    name = (node.name or "").strip()
    if name in generic_names:
        return True
    return node.node_type == "topic" and len(_node_name_tokens(node)) <= 2


def relevance_threshold(
    node: KnowledgeNode,
    segment: Segment,
    video: Optional[VideoCache] = None,
) -> float:
    threshold = MEDIUM_CONFIDENCE_THRESHOLD
    segment_text = _normalize_text(segment.cleaned_text or segment.raw_text)
    title_text = _normalize_text(video.title if video else "")
    if segment.source_type == "basic":
        threshold += 0.14
    if node.node_type == "topic":
        threshold += 0.08
    if _is_generic_node(node):
        threshold += 0.06
    if not _has_name_or_alias_match(node, segment_text) and not _has_name_or_alias_match(node, title_text):
        threshold += 0.05
    return min(0.85, threshold)


def build_reason(
    node: KnowledgeNode,
    segment_text: str,
    semantic_boost: float = 0.0,
    support_count: int = 1,
    video_title: str = "",
) -> str:
    haystack = _normalize_text(segment_text)
    if not haystack:
        return "片段文本缺失"

    if _normalize_text(node.name) and _normalize_text(node.name) in haystack:
        return "关键词重合"

    for alias in node.aliases or []:
        alias_norm = _normalize_text(alias)
        if alias_norm and alias_norm in haystack:
            return f"别名命中：{alias}"

    title_text = _normalize_text(video_title)
    if title_text and _has_name_or_alias_match(node, title_text):
        return "视频标题匹配"

    if semantic_boost >= 0.72:
        return "语义相似"

    if support_count >= 2:
        return "多个视频共同支持"

    return "来自已绑定知识片段"


def confidence_level_from_score(score: float) -> str:
    if score >= HIGH_CONFIDENCE_THRESHOLD:
        return "high"
    if score >= MEDIUM_CONFIDENCE_THRESHOLD:
        return "medium"
    return "low"


def is_relevant_score(score: float) -> bool:
    return score >= MEDIUM_CONFIDENCE_THRESHOLD


def rule_score_segment_match(
    node: KnowledgeNode,
    link: NodeSegmentLink,
    segment: Segment,
    video: Optional[VideoCache] = None,
) -> float:
    text = _normalize_text(segment.cleaned_text or segment.raw_text)
    score = float(link.confidence or 0.0)
    node_tokens = _node_name_tokens(node)
    full_node_tokens = _node_context_tokens(node)
    segment_tokens = _tokenize(segment.cleaned_text or segment.raw_text or "")
    title_tokens = _title_tokens(video)
    overlap_ratio = _jaccard(node_tokens, segment_tokens)
    context_overlap_ratio = _jaccard(full_node_tokens, segment_tokens)
    title_overlap = _jaccard(node_tokens, title_tokens)

    name_norm = _normalize_text(node.name)
    if name_norm and name_norm in text:
        score += 0.45

    for alias in node.aliases or []:
        alias_norm = _normalize_text(alias)
        if alias_norm and alias_norm in text:
            score += 0.2
            break

    relation = (link.relation or "").lower()
    if relation in {"explains", "demonstrates"}:
        score += 0.08

    if title_overlap > 0:
        score += min(0.12, title_overlap * 0.18)

    score += min(0.18, overlap_ratio * 0.45)
    score += min(0.08, context_overlap_ratio * 0.18)

    text_len = len((segment.cleaned_text or segment.raw_text or "").strip())
    if 20 <= text_len <= 240:
        score += 0.05
    elif text_len < 10:
        score -= 0.15

    if segment.is_peak:
        score += 0.04
    if (segment.knowledge_density or 0.0) >= 0.45:
        score += 0.05

    if segment.source_type == "basic":
        score -= 0.2
        if title_overlap > 0 or (name_norm and name_norm in _normalize_text(video.title if video else "")):
            score += 0.08

    has_text_match = _has_name_or_alias_match(node, text)
    has_title_match = _has_name_or_alias_match(node, _normalize_text(video.title if video else ""))
    if not has_text_match and not has_title_match and overlap_ratio <= 0.01:
        score -= 0.22

    if node.node_type == "topic" and not has_text_match and title_overlap < 0.15:
        score -= 0.12

    if _is_generic_node(node) and not has_text_match and context_overlap_ratio < 0.08:
        score -= 0.14

    return max(0.0, min(1.0, score))


def build_evidence_features(
    node: KnowledgeNode,
    link: Optional[NodeSegmentLink],
    segment: Segment,
    video: Optional[VideoCache] = None,
) -> tuple[dict[str, float], list[str]]:
    segment_text = segment.cleaned_text or segment.raw_text or ""
    node_tokens = _node_context_tokens(node)
    segment_tokens = _tokenize(segment_text)
    title_tokens = _title_tokens(video)
    overlap = len(set(node_tokens) & set(segment_tokens))
    title_overlap = len(set(node_tokens) & set(title_tokens))
    text_len = len(segment_text.strip())

    numeric = {
        "link_confidence": float(link.confidence or 0.0) if link else 0.0,
        "node_confidence": float(node.confidence or 0.0),
        "node_source_count": float(node.source_count or 1.0),
        "segment_confidence": float(segment.confidence or 0.0),
        "text_len_bucket": min(6.0, text_len / 80.0),
        "knowledge_density": float(segment.knowledge_density or 0.0),
        "overlap_count": float(overlap),
        "overlap_ratio": _jaccard(node_tokens, segment_tokens),
        "title_overlap": float(title_overlap),
        "name_exact_match": 1.0 if _normalize_text(node.name) in _normalize_text(segment_text) else 0.0,
        "has_alias_match": 1.0 if any(_normalize_text(alias) in _normalize_text(segment_text) for alias in (node.aliases or [])) else 0.0,
        "is_peak": 1.0 if segment.is_peak else 0.0,
        "is_basic_source": 1.0 if (segment.source_type or "") == "basic" else 0.0,
        "is_topic_node": 1.0 if node.node_type == "topic" else 0.0,
        "is_generic_node": 1.0 if _is_generic_node(node) else 0.0,
    }

    token_features = [
        f"node_type::{node.node_type}",
        f"relation::{(link.relation if link else 'unknown')}",
        f"content_source::{segment.source_type or 'unknown'}",
    ]
    token_features.extend(f"node::{token}" for token in node_tokens[:8])
    token_features.extend(f"title::{token}" for token in title_tokens[:8])
    token_features.extend(f"seg::{token}" for token in segment_tokens[:16])
    token_features.extend(f"overlap::{token}" for token in set(node_tokens) & set(segment_tokens))
    return numeric, token_features


def build_features_from_record(record: dict[str, Any]) -> tuple[dict[str, float], list[str]]:
    node_tokens = _tokenize(" ".join(filter(None, [record.get("node_name", ""), record.get("node_definition", "")])))
    segment_text = record.get("segment_text", "") or ""
    segment_tokens = _tokenize(segment_text)
    title_tokens = _tokenize(record.get("video_title", "") or "")
    overlap = len(set(node_tokens) & set(segment_tokens))
    title_overlap = len(set(node_tokens) & set(title_tokens))
    text_len = len(segment_text.strip())

    numeric = {
        "link_confidence": float(record.get("link_confidence", 0.0) or 0.0),
        "node_confidence": float(record.get("node_confidence", 0.0) or 0.0),
        "node_source_count": float(record.get("node_source_count", 1.0) or 1.0),
        "segment_confidence": float(record.get("segment_confidence", 0.0) or 0.0),
        "text_len_bucket": min(6.0, text_len / 80.0),
        "knowledge_density": float(record.get("knowledge_density", 0.0) or 0.0),
        "overlap_count": float(overlap),
        "overlap_ratio": _jaccard(node_tokens, segment_tokens),
        "title_overlap": float(title_overlap),
        "name_exact_match": 1.0 if _normalize_text(record.get("node_name", "")) in _normalize_text(segment_text) else 0.0,
        "has_alias_match": 1.0 if any(_normalize_text(alias) in _normalize_text(segment_text) for alias in (record.get("node_aliases") or [])) else 0.0,
        "is_peak": 1.0 if record.get("is_peak") else 0.0,
        "is_basic_source": 1.0 if (record.get("segment_source_type") or "") == "basic" else 0.0,
        "is_topic_node": 1.0 if record.get("node_type") == "topic" else 0.0,
        "is_generic_node": 1.0 if str(record.get("node_name", "")).strip() in {"学习", "知识", "方法", "技术", "系统", "工具", "应用", "内容", "视频"} else 0.0,
    }
    token_features = [
        f"node_type::{record.get('node_type', 'concept')}",
        f"relation::{record.get('relation', 'unknown')}",
        f"content_source::{record.get('segment_source_type', 'unknown')}",
    ]
    token_features.extend(f"node::{token}" for token in node_tokens[:8])
    token_features.extend(f"title::{token}" for token in title_tokens[:8])
    token_features.extend(f"seg::{token}" for token in segment_tokens[:16])
    token_features.extend(f"overlap::{token}" for token in set(node_tokens) & set(segment_tokens))
    return numeric, token_features


class EvidenceRanker:
    def __init__(self, model_path: Optional[str] = None):
        self.model_path = Path(model_path or settings.evidence_ranker_model_path)
        self.load_error: Optional[str] = None
        self.disabled_reason: Optional[str] = None
        self.model = self._try_load()

    def _try_load(self) -> Optional[HashedBinaryLogisticModel]:
        if not settings.evidence_ranker_enabled:
            self.disabled_reason = "disabled_by_config"
            return None
        if not self.model_path.exists():
            self.disabled_reason = "model_file_missing"
            return None
        try:
            return HashedBinaryLogisticModel.load(self.model_path)
        except Exception as exc:
            self.load_error = f"{type(exc).__name__}: {exc}"
            self.disabled_reason = "model_load_failed"
            return None

    @property
    def is_enabled(self) -> bool:
        return self.model is not None

    def score(
        self,
        node: KnowledgeNode,
        link: NodeSegmentLink,
        segment: Segment,
        video: Optional[VideoCache] = None,
    ) -> dict[str, float | bool | str]:
        base_score = rule_score_segment_match(node, link, segment, video)
        threshold = relevance_threshold(node, segment, video)
        if not self.model:
            confidence_level = confidence_level_from_score(base_score)
            return {
                "score": base_score,
                "model_score": base_score,
                "rule_score": base_score,
                "used_model": False,
                "is_relevant": base_score >= threshold,
                "confidence_level": confidence_level,
                "threshold": threshold,
            }

        numeric, tokens = build_evidence_features(node, link, segment, video)
        model_score = self.model.predict_proba(numeric, tokens)
        final_score = max(0.0, min(1.0, base_score * 0.55 + model_score * 0.45))
        confidence_level = confidence_level_from_score(final_score)
        return {
            "score": final_score,
            "model_score": model_score,
            "rule_score": base_score,
            "used_model": True,
            "is_relevant": final_score >= threshold,
            "confidence_level": confidence_level,
            "threshold": threshold,
        }

    def score_record(self, record: dict[str, Any]) -> EvidenceInference:
        rule_score = float(record.get("rule_score", 0.0) or 0.0)
        numeric_features = record.get("numeric_features")
        token_features = record.get("token_features")
        has_explicit_rule_score = "rule_score" in record
        if not self.model:
            score = rule_score
            return EvidenceInference(
                relevance_score=score,
                model_score=score,
                rule_score=rule_score,
                is_relevant=is_relevant_score(score),
                confidence_level=confidence_level_from_score(score),
                used_model=False,
            )
        if isinstance(numeric_features, dict) and isinstance(token_features, list):
            numeric = {str(key): float(value) for key, value in numeric_features.items()}
            tokens = [str(token) for token in token_features]
            if not rule_score and "rule_score" in numeric:
                rule_score = float(numeric.get("rule_score", 0.0) or 0.0)
                has_explicit_rule_score = True
        else:
            numeric, tokens = build_features_from_record(record)
        model_score = self.model.predict_proba(numeric, tokens)
        if has_explicit_rule_score:
            score = max(0.0, min(1.0, rule_score * 0.55 + model_score * 0.45))
        else:
            score = model_score
        return EvidenceInference(
            relevance_score=score,
            model_score=model_score,
            rule_score=rule_score,
            is_relevant=is_relevant_score(score),
            confidence_level=confidence_level_from_score(score),
            used_model=True,
        )


@lru_cache(maxsize=1)
def get_evidence_ranker() -> EvidenceRanker:
    return EvidenceRanker()
