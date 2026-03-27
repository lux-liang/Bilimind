"""
单条或批量推理知识点-视频片段相关性。
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


def load_payload(path: Path) -> list[dict]:
    if path.suffix.lower() == ".jsonl":
        with path.open("r", encoding="utf-8") as handle:
            return [json.loads(line) for line in handle if line.strip()]
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        return [payload]
    raise ValueError("输入必须是 JSON object / JSON array / JSONL")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="待推理样本文件，支持 json/jsonl")
    parser.add_argument("--model", default=settings.evidence_ranker_model_path)
    parser.add_argument("--output", default=None, help="可选，将结果写入文件")
    args = parser.parse_args()

    rows = load_payload(Path(args.input))
    ranker = EvidenceRanker(model_path=args.model)
    results = []
    for row in rows:
        inference = ranker.score_record(row)
        results.append({
            **row,
            "relevance_score": round(inference.relevance_score, 4),
            "model_score": round(inference.model_score, 4),
            "rule_score": round(inference.rule_score, 4),
            "is_relevant": inference.is_relevant,
            "confidence_level": inference.confidence_level,
            "used_model": inference.used_model,
        })

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
