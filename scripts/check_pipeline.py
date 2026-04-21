#!/usr/bin/env python3
"""
Validate a generated BiliMind Harness artifact directory.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REQUIRED_FILES = [
    "raw_metadata.json",
    "raw_transcript.json",
    "extracted_nodes.json",
    "merged_nodes.json",
    "merged_graph.json",
    "learning_path.json",
    "evidence_map.json",
    "validation_report.json",
    "render_bundle.json",
    "pipeline_trace.json",
    "summary.json",
]


def _load(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _latest_run(root: Path) -> Path:
    runs = [p for p in root.iterdir() if p.is_dir()] if root.exists() else []
    if not runs:
        raise FileNotFoundError(f"No artifact runs found in {root}")
    return max(runs, key=lambda p: p.stat().st_mtime)


def main() -> int:
    parser = argparse.ArgumentParser(description="Check BiliMind Harness artifacts")
    parser.add_argument("artifact_dir", nargs="?", default="", help="Run directory; defaults to latest artifacts/harness run")
    args = parser.parse_args()

    run_dir = Path(args.artifact_dir) if args.artifact_dir else _latest_run(ROOT / "artifacts" / "harness")
    if not run_dir.is_absolute():
        run_dir = ROOT / run_dir

    missing = [name for name in REQUIRED_FILES if not (run_dir / name).exists()]
    if missing:
        print(json.dumps({"passed": False, "missing": missing, "artifact_dir": str(run_dir)}, ensure_ascii=False, indent=2))
        return 1

    graph = _load(run_dir / "merged_graph.json")
    path = _load(run_dir / "learning_path.json")
    evidence_map = _load(run_dir / "evidence_map.json")
    validation = _load(run_dir / "validation_report.json")
    render_bundle = _load(run_dir / "render_bundle.json")
    trace = _load(run_dir / "pipeline_trace.json")

    checks = {
        "has_nodes": len(graph.get("nodes", [])) > 0,
        "has_evidence": len(graph.get("evidence_links", [])) > 0,
        "has_evidence_packets": len(evidence_map.get("evidence_packets", [])) > 0,
        "has_learning_path": len(path.get("steps", [])) > 0,
        "has_render_bundle": len(render_bundle.get("concept_cards", [])) > 0,
        "stage_trace_complete": len(trace.get("stages", [])) >= 8,
        "validation_passed": validation.get("passed") is True,
    }
    passed = all(checks.values())
    print(json.dumps({
        "passed": passed,
        "artifact_dir": str(run_dir),
        "checks": checks,
        "validation_summary": validation.get("summary", {}),
        "stage_order": trace.get("stage_order", []),
    }, ensure_ascii=False, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
