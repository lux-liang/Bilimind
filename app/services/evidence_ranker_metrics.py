"""
Evidence ranker evaluation helpers.

统一离线训练、评估、答辩指标口径，避免脚本各自维护一套规则。
"""
from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from app.services.evidence_ranker import MEDIUM_CONFIDENCE_THRESHOLD


def _safe_div(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 0.0
    return numerator / denominator


def compute_auc(labels: Iterable[int], scores: Iterable[float]) -> float:
    pairs = [(int(label), float(score)) for label, score in zip(labels, scores)]
    positives = sum(1 for label, _ in pairs if label == 1)
    negatives = sum(1 for label, _ in pairs if label == 0)
    if positives == 0 or negatives == 0:
        return 0.0

    ranked = sorted(enumerate(pairs), key=lambda item: item[1][1])
    rank_sum = 0.0
    index = 0
    while index < len(ranked):
        score = ranked[index][1][1]
        end = index + 1
        while end < len(ranked) and ranked[end][1][1] == score:
            end += 1
        avg_rank = (index + 1 + end) / 2.0
        for _, (label, _) in ranked[index:end]:
            if label == 1:
                rank_sum += avg_rank
        index = end

    return (rank_sum - positives * (positives + 1) / 2.0) / (positives * negatives)


def compute_classification_metrics(
    labels: Iterable[int],
    scores: Iterable[float],
    threshold: float = MEDIUM_CONFIDENCE_THRESHOLD,
) -> dict[str, float]:
    label_list = [int(label) for label in labels]
    score_list = [float(score) for score in scores]
    predictions = [1 if score >= threshold else 0 for score in score_list]

    tp = sum(1 for label, pred in zip(label_list, predictions) if label == 1 and pred == 1)
    tn = sum(1 for label, pred in zip(label_list, predictions) if label == 0 and pred == 0)
    fp = sum(1 for label, pred in zip(label_list, predictions) if label == 0 and pred == 1)
    fn = sum(1 for label, pred in zip(label_list, predictions) if label == 1 and pred == 0)
    total = len(label_list)

    precision = _safe_div(tp, tp + fp)
    recall = _safe_div(tp, tp + fn)
    f1 = _safe_div(2 * precision * recall, precision + recall)
    accuracy = _safe_div(tp + tn, total)

    return {
        "threshold": threshold,
        "accuracy": accuracy,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "auc": compute_auc(label_list, score_list),
        "tp": tp,
        "tn": tn,
        "fp": fp,
        "fn": fn,
        "samples": total,
    }


def compute_query_metrics(
    rows: list[dict],
    score_key: str = "relevance_score",
    threshold: float = MEDIUM_CONFIDENCE_THRESHOLD,
) -> dict[str, float]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        query_id = str(row.get("query_id") or row.get("sample_id") or row.get("node_id") or "unknown")
        groups[query_id].append(row)

    displayed = 0
    top1_correct = 0
    top1_wrong = 0
    empty = 0

    for query_rows in groups.values():
        ranked = sorted(
            query_rows,
            key=lambda item: (
                -float(item.get(score_key, 0.0) or 0.0),
                -float(item.get("rule_score", 0.0) or 0.0),
                int(item.get("segment_id") or 0),
            ),
        )
        top = ranked[0]
        if float(top.get(score_key, 0.0) or 0.0) < threshold:
            empty += 1
            continue
        displayed += 1
        if int(top.get("label", 0)) == 1:
            top1_correct += 1
        else:
            top1_wrong += 1

    query_total = len(groups)
    return {
        "queries": query_total,
        "displayed_queries": displayed,
        "empty_queries": empty,
        "top1_precision": _safe_div(top1_correct, displayed),
        "error_display_rate": _safe_div(top1_wrong, query_total),
        "empty_state_rate": _safe_div(empty, query_total),
        "coverage": _safe_div(displayed, query_total),
    }
