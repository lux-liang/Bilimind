#!/usr/bin/env python3
"""
Validate BiliMind demo/sample output directories.

This script is intended for competition demos where judges need a single
command to verify that the committed sample outputs still satisfy the Harness
contracts.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SAMPLE_OUTPUT_ROOT = ROOT / "demo" / "sample_output"


def _load(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _iter_runs(target: Path) -> list[Path]:
    if target.is_dir() and (target / "summary.json").exists():
        return [target]
    if not target.exists():
        raise FileNotFoundError(f"Output path not found: {target}")
    return sorted([path for path in target.iterdir() if path.is_dir() and (path / "summary.json").exists()])


def _validate_run(run_dir: Path) -> dict:
    summary = _load(run_dir / "summary.json")
    validation = _load(run_dir / "validation_report.json")
    evidence_map = _load(run_dir / "evidence_map.json")
    render_bundle = _load(run_dir / "render_bundle.json")
    trace = _load(run_dir / "pipeline_trace.json")

    checks = {
        "validation_passed": validation.get("passed") is True,
        "has_stage_order": trace.get("stage_order") == [
            "ingest",
            "transcript",
            "extract",
            "merge",
            "graph",
            "plan",
            "evidence",
            "validate",
            "render",
        ],
        "has_evidence_packets": summary.get("stats", {}).get("evidence_packet_count", 0) > 0,
        "all_learning_steps_covered": validation.get("summary", {}).get("uncovered_learning_steps", 0) == 0,
        "render_bundle_present": len(render_bundle.get("timeline", [])) > 0,
        "coverage_matches_steps": len(evidence_map.get("coverage", [])) == summary.get("stats", {}).get("learning_step_count", 0),
    }
    return {
        "run_dir": str(run_dir),
        "passed": all(checks.values()),
        "checks": checks,
        "stats": summary.get("stats", {}),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate committed BiliMind sample outputs")
    parser.add_argument("path", nargs="?", default=str(SAMPLE_OUTPUT_ROOT))
    args = parser.parse_args()

    target = Path(args.path)
    if not target.is_absolute():
        target = ROOT / target

    reports = [_validate_run(run_dir) for run_dir in _iter_runs(target)]
    passed = all(report["passed"] for report in reports)
    print(json.dumps({"passed": passed, "reports": reports}, ensure_ascii=False, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
