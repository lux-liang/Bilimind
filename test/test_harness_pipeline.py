import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.harness_pipeline import HarnessPipeline


def test_sample_harness_pipeline(tmp_path):
    pipeline = HarnessPipeline(output_root=tmp_path)
    result = pipeline.run(output_dir=tmp_path / "run")

    summary = result["summary"]
    validation = result["validation_report"]
    graph = result["merged_graph"]

    assert summary["harness"]["validation_passed"] is True
    assert summary["stats"]["node_count"] >= 3
    assert summary["stats"]["evidence_count"] >= 3
    assert validation["passed"] is True
    assert graph["nodes"]
    assert graph["evidence_links"]
    assert (tmp_path / "run" / "pipeline_trace.json").exists()
