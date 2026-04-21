#!/usr/bin/env python3
"""
Run the BiliMind Harness demo pipeline.

This script is intentionally network-free by default. It uses local sample
metadata/transcripts and writes replayable artifacts to artifacts/harness/.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.harness_pipeline import DEFAULT_SAMPLE_BVID, HarnessPipeline


def main() -> int:
    parser = argparse.ArgumentParser(description="Run BiliMind Harness demo pipeline")
    parser.add_argument("--bvid", default=DEFAULT_SAMPLE_BVID, help="Sample or real BVID")
    parser.add_argument("--datasource", default="sample", choices=["sample", "real", "local"])
    parser.add_argument("--transcript-source", default="sample", choices=["sample", "api", "asr", "local"])
    parser.add_argument("--output-dir", default="", help="Optional artifact output directory")
    args = parser.parse_args()

    pipeline = HarnessPipeline()
    result = pipeline.run(
        bvid=args.bvid,
        datasource=args.datasource,
        transcript_source=args.transcript_source,
        output_dir=args.output_dir or None,
    )

    summary = result["summary"]
    print(json.dumps({
        "artifact_dir": result["artifact_dir"],
        "video": summary["video"],
        "stats": summary["stats"],
        "validation_passed": summary["harness"]["validation_passed"],
    }, ensure_ascii=False, indent=2))
    return 0 if summary["harness"]["validation_passed"] else 1


if __name__ == "__main__":
    os.chdir(ROOT)
    raise SystemExit(main())
