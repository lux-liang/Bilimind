"""
训练证据相关性判别器。
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402
from app.services.evidence_ranker_metrics import compute_classification_metrics  # noqa: E402
from app.services.lightweight_models import HashedBinaryLogisticModel, SparseSample  # noqa: E402


def load_samples(path: Path) -> list[SparseSample]:
    samples: list[SparseSample] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            samples.append(SparseSample(
                label=float(row["label"]),
                numeric_features=row.get("numeric_features") or {},
                token_features=list(row.get("token_features") or []),
            ))
    return samples


def resolve_dataset_path(path_value: str, split_name: str) -> Path:
    path = Path(path_value)
    if path.is_dir():
        return path / f"{split_name}.jsonl"
    return path


def evaluate_model(model: HashedBinaryLogisticModel, samples: list[SparseSample]) -> dict[str, float]:
    labels = [1 if sample.label > 0.5 else 0 for sample in samples]
    scores = [model.predict_proba(sample.numeric_features, sample.token_features) for sample in samples]
    return compute_classification_metrics(labels, scores)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=str(ROOT / "data" / "training" / "evidence_ranker"))
    parser.add_argument("--val-input", default=None, help="验证集 jsonl；为空时若 --input 是目录则自动读取 val.jsonl")
    parser.add_argument("--output", default=settings.evidence_ranker_model_path)
    parser.add_argument("--epochs", type=int, default=10)
    parser.add_argument("--lr", type=float, default=0.06)
    parser.add_argument("--buckets", type=int, default=768)
    parser.add_argument("--l2", type=float, default=1e-4)
    args = parser.parse_args()

    train_path = resolve_dataset_path(args.input, "train")
    if not train_path.exists():
        raise FileNotFoundError(f"训练集不存在: {train_path}")
    samples = load_samples(train_path)
    positives = sum(1 for sample in samples if sample.label > 0.5)
    negatives = max(1, len(samples) - positives)
    model = HashedBinaryLogisticModel(buckets=args.buckets, metadata={
        "task": "evidence_ranker",
        "samples": len(samples),
        "positives": positives,
        "negatives": negatives,
    })
    model.fit(
        samples,
        epochs=args.epochs,
        lr=args.lr,
        l2=args.l2,
        positive_weight=max(1.0, negatives / max(1, positives)),
    )
    model.save(args.output)

    train_metrics = evaluate_model(model, samples) if samples else {}
    print(f"Saved evidence ranker to {args.output}")
    if train_metrics:
        print(
            "Train "
            f"samples={len(samples)} positives={positives} negatives={negatives} "
            f"accuracy={train_metrics['accuracy']:.3f} precision={train_metrics['precision']:.3f} "
            f"recall={train_metrics['recall']:.3f} f1={train_metrics['f1']:.3f} auc={train_metrics['auc']:.3f}"
        )

    val_path = Path(args.val_input) if args.val_input else None
    if val_path is None and Path(args.input).is_dir():
        candidate = Path(args.input) / "val.jsonl"
        if candidate.exists():
            val_path = candidate
    if val_path and val_path.exists():
        val_samples = load_samples(val_path)
        val_metrics = evaluate_model(model, val_samples)
        print(
            "Val "
            f"samples={len(val_samples)} accuracy={val_metrics['accuracy']:.3f} "
            f"precision={val_metrics['precision']:.3f} recall={val_metrics['recall']:.3f} "
            f"f1={val_metrics['f1']:.3f} auc={val_metrics['auc']:.3f}"
        )


if __name__ == "__main__":
    main()
