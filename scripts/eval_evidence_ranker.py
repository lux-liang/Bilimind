"""
评估知识点-视频片段相关性判别器。

输出：
1. 模型级指标：Accuracy / Precision / Recall / F1 / AUC
2. 系统级指标：Top-1 evidence precision / 错误证据展示率 / 空状态触发率
3. 基线对比：仅规则分 vs 规则分 + 判别器
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402
from app.services.evidence_ranker import EvidenceRanker  # noqa: E402
from app.services.evidence_ranker_metrics import compute_classification_metrics, compute_query_metrics  # noqa: E402


def resolve_dataset_path(path_value: str, split_name: str) -> Path:
    path = Path(path_value)
    if path.is_dir():
        return path / f"{split_name}.jsonl"
    return path


def load_rows(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            rows.append(json.loads(line))
    return rows


def attach_scores(rows: list[dict], ranker: EvidenceRanker) -> list[dict]:
    enriched: list[dict] = []
    for row in rows:
        result = ranker.score_record(row)
        enriched.append({
            **row,
            "relevance_score": result.relevance_score,
            "model_score": result.model_score,
            "rule_score": float(row.get("rule_score", 0.0) or 0.0),
            "is_relevant": result.is_relevant,
            "confidence_level": result.confidence_level,
        })
    return enriched


def summarize(rows: list[dict], score_key: str) -> dict[str, float]:
    labels = [int(row["label"]) for row in rows]
    scores = [float(row.get(score_key, 0.0) or 0.0) for row in rows]
    metrics = compute_classification_metrics(labels, scores)
    metrics.update(compute_query_metrics(rows, score_key=score_key))
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=str(ROOT / "data" / "training" / "evidence_ranker"))
    parser.add_argument("--split", default="test", choices=["train", "val", "test"])
    parser.add_argument("--model", default=settings.evidence_ranker_model_path)
    parser.add_argument("--output", default=None, help="可选，将详细评分结果写出为 JSON")
    parser.add_argument("--markdown-out", default=None, help="可选，将评估摘要写出为 Markdown，便于 PPT/答辩使用")
    args = parser.parse_args()

    dataset_path = resolve_dataset_path(args.input, args.split)
    if not dataset_path.exists():
        raise FileNotFoundError(f"评估集不存在: {dataset_path}")

    rows = load_rows(dataset_path)
    ranker = EvidenceRanker(model_path=args.model)
    scored_rows = attach_scores(rows, ranker)

    baseline_metrics = summarize(scored_rows, "rule_score")
    rerank_metrics = summarize(scored_rows, "relevance_score")
    payload = {
        "dataset": str(dataset_path),
        "samples": len(scored_rows),
        "model_path": args.model,
        "ranker_enabled": ranker.is_enabled,
        "ranker_disabled_reason": ranker.disabled_reason,
        "ranker_load_error": ranker.load_error,
        "baseline_rule_only": baseline_metrics,
        "rerank_classifier": rerank_metrics,
        "delta": {
            "top1_precision": rerank_metrics["top1_precision"] - baseline_metrics["top1_precision"],
            "error_display_rate": rerank_metrics["error_display_rate"] - baseline_metrics["error_display_rate"],
            "empty_state_rate": rerank_metrics["empty_state_rate"] - baseline_metrics["empty_state_rate"],
            "f1": rerank_metrics["f1"] - baseline_metrics["f1"],
            "auc": rerank_metrics["auc"] - baseline_metrics["auc"],
        },
    }

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps({
            "summary": payload,
            "rows": scored_rows,
        }, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.markdown_out:
        md_path = Path(args.markdown_out)
        md_path.parent.mkdir(parents=True, exist_ok=True)
        md = [
            "# Evidence Ranker Evaluation",
            "",
            f"- Dataset: `{dataset_path}`",
            f"- Samples: `{len(scored_rows)}`",
            f"- Ranker Enabled: `{ranker.is_enabled}`",
            f"- Disabled Reason: `{ranker.disabled_reason or 'n/a'}`",
            f"- Load Error: `{ranker.load_error or 'n/a'}`",
            "",
            "| 方法 | Accuracy | Precision | Recall | F1 | AUC | Top-1 Precision | Error Display Rate | Empty State Rate | Coverage |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
            (
                f"| 仅规则分 | {baseline_metrics['accuracy']:.3f} | {baseline_metrics['precision']:.3f} | "
                f"{baseline_metrics['recall']:.3f} | {baseline_metrics['f1']:.3f} | {baseline_metrics['auc']:.3f} | "
                f"{baseline_metrics['top1_precision']:.3f} | {baseline_metrics['error_display_rate']:.3f} | "
                f"{baseline_metrics['empty_state_rate']:.3f} | {baseline_metrics['coverage']:.3f} |"
            ),
            (
                f"| 规则分 + 判别器 | {rerank_metrics['accuracy']:.3f} | {rerank_metrics['precision']:.3f} | "
                f"{rerank_metrics['recall']:.3f} | {rerank_metrics['f1']:.3f} | {rerank_metrics['auc']:.3f} | "
                f"{rerank_metrics['top1_precision']:.3f} | {rerank_metrics['error_display_rate']:.3f} | "
                f"{rerank_metrics['empty_state_rate']:.3f} | {rerank_metrics['coverage']:.3f} |"
            ),
            "",
            "## Delta",
            "",
            f"- F1: `{payload['delta']['f1']:+.3f}`",
            f"- AUC: `{payload['delta']['auc']:+.3f}`",
            f"- Top-1 Precision: `{payload['delta']['top1_precision']:+.3f}`",
            f"- Error Display Rate: `{payload['delta']['error_display_rate']:+.3f}`",
            f"- Empty State Rate: `{payload['delta']['empty_state_rate']:+.3f}`",
        ]
        md_path.write_text("\n".join(md), encoding="utf-8")

    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
