"""
训练 Organizer 轻量分类器。
"""
import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402
from app.services.lightweight_models import HashedMulticlassOVRModel  # noqa: E402
from app.services.video_classifier import OrganizerClassifierBundle  # noqa: E402


TASKS = ["primary_subject", "content_type", "difficulty_level", "value_tier"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=str(ROOT / "data" / "training" / "organizer_classifier.jsonl"))
    parser.add_argument("--output", default=settings.organizer_classifier_model_path)
    parser.add_argument("--epochs", type=int, default=8)
    parser.add_argument("--lr", type=float, default=0.06)
    parser.add_argument("--buckets", type=int, default=768)
    args = parser.parse_args()

    rows = []
    labels_by_task: dict[str, set[str]] = defaultdict(set)
    with Path(args.input).open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            rows.append(row)
            for task in TASKS:
                labels_by_task[task].add(row["labels"][task])

    bundle = OrganizerClassifierBundle()
    for task in TASKS:
        dataset = [
            (row["labels"][task], row["numeric_features"], row["token_features"])
            for row in rows
        ]
        model = HashedMulticlassOVRModel(labels=sorted(labels_by_task[task]), buckets=args.buckets)
        model.fit(dataset, epochs=args.epochs, lr=args.lr)
        bundle.tasks[task] = model

    bundle.save(args.output)
    print(f"Saved organizer classifier to {args.output}")
    for task in TASKS:
        correct = 0
        for row in rows:
            pred, _, _ = bundle.tasks[task].predict(row["numeric_features"], row["token_features"])
            if pred == row["labels"][task]:
                correct += 1
        accuracy = correct / len(rows) if rows else 0.0
        print(f"{task}: labels={len(labels_by_task[task])} train_accuracy={accuracy:.3f}")


if __name__ == "__main__":
    main()
