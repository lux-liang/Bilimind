"""
BiliMind Harness pipeline.

This module makes the existing BiliMind knowledge workflow explicit and
replayable for demo and competition evaluation:

ingest -> transcript -> extract -> merge -> graph -> plan -> validate

The production compiler can still use Bilibili/ASR/LLM services. This lightweight
pipeline adds deterministic sample mode, JSON artifacts, stage traces, and a
validation feedback loop without replacing the current product code.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


PIPELINE_VERSION = "harness-0.1"
DEFAULT_SAMPLE_BVID = "BVDEMOHARNESS01"
STAGE_ORDER = [
    "ingest",
    "transcript",
    "extract",
    "merge",
    "graph",
    "plan",
    "validate",
]


@dataclass
class StageTrace:
    name: str
    status: str
    duration_ms: int
    input_summary: str
    output_summary: str
    warnings: list[str]
    artifact: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "input_summary": self.input_summary,
            "output_summary": self.output_summary,
            "warnings": self.warnings,
            "artifact": self.artifact,
        }


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_name(name: str) -> str:
    name = name.strip().lower()
    name = re.sub(r"\s+", " ", name)
    name = re.sub(r"[（(].*?[）)]", "", name).strip()
    return name


def _safe_name(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "_", name).strip("_") or "artifact"


def _fmt_time(seconds: Optional[float]) -> str:
    if seconds is None:
        return ""
    total = int(seconds)
    m, s = divmod(total, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


class SampleHarnessTool:
    """Local datasource adapter used when real tools/API are unavailable."""

    def __init__(self, repo_root: Optional[Path] = None):
        self.root = repo_root or _repo_root()
        self.video_path = self.root / "demo" / "sample_videos.json"
        self.transcript_dir = self.root / "demo" / "sample_transcripts"

    def load_video(self, bvid: str = DEFAULT_SAMPLE_BVID) -> dict[str, Any]:
        videos = _read_json(self.video_path)
        for video in videos:
            if video.get("bvid") == bvid:
                return dict(video)
        if not videos:
            raise FileNotFoundError("demo/sample_videos.json has no sample videos")
        return dict(videos[0])

    def load_transcript(self, bvid: str) -> dict[str, Any]:
        path = self.transcript_dir / f"{bvid}.json"
        return _read_json(path)


class HarnessPipeline:
    """
    Deterministic Harness workflow with artifact persistence.

    This class intentionally uses lightweight extraction rules in demo mode.
    Real Bilibili/ASR/LLM integrations remain in existing service modules and are
    represented here as datasource adapters.
    """

    def __init__(
        self,
        output_root: str | Path = "artifacts/harness",
        repo_root: Optional[Path] = None,
    ):
        self.root = repo_root or _repo_root()
        self.output_root = Path(output_root)
        if not self.output_root.is_absolute():
            self.output_root = self.root / self.output_root
        self.sample_tool = SampleHarnessTool(self.root)

    def run(
        self,
        bvid: str = DEFAULT_SAMPLE_BVID,
        datasource: str = "sample",
        transcript_source: str = "sample",
        output_dir: Optional[str | Path] = None,
    ) -> dict[str, Any]:
        run_id = f"{_safe_name(bvid)}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        run_dir = Path(output_dir) if output_dir else self.output_root / run_id
        if not run_dir.is_absolute():
            run_dir = self.root / run_dir
        run_dir.mkdir(parents=True, exist_ok=True)

        traces: list[StageTrace] = []
        stage_outputs: dict[str, Any] = {}

        metadata, trace = self._run_stage(
            "ingest",
            lambda: self._stage_ingest(bvid, datasource),
            input_summary=f"bvid={bvid}, datasource={datasource}",
            artifact_path=run_dir / "raw_metadata.json",
        )
        traces.append(trace)
        stage_outputs["metadata"] = metadata

        transcript, trace = self._run_stage(
            "transcript",
            lambda: self._stage_transcript(metadata, transcript_source),
            input_summary=f"bvid={metadata['bvid']}, transcript_source={transcript_source}",
            artifact_path=run_dir / "raw_transcript.json",
        )
        traces.append(trace)
        stage_outputs["transcript"] = transcript

        extracted, trace = self._run_stage(
            "extract",
            lambda: self._stage_extract(metadata, transcript),
            input_summary=f"{len(transcript.get('segments', []))} timestamped transcript segments",
            artifact_path=run_dir / "extracted_nodes.json",
        )
        traces.append(trace)
        stage_outputs["extracted"] = extracted

        merged_nodes, trace = self._run_stage(
            "merge",
            lambda: self._stage_merge(metadata, extracted),
            input_summary=(
                f"{len(extracted.get('concept_candidates', []))} concept candidates, "
                f"{len(extracted.get('claim_candidates', []))} claim candidates"
            ),
            artifact_path=run_dir / "merged_nodes.json",
        )
        traces.append(trace)
        stage_outputs["merged_nodes"] = merged_nodes

        graph, trace = self._run_stage(
            "graph",
            lambda: self._stage_graph(metadata, transcript, merged_nodes),
            input_summary=(
                f"{len(merged_nodes.get('nodes', []))} merged nodes, "
                f"{len(merged_nodes.get('claims', []))} grounded claims"
            ),
            artifact_path=run_dir / "merged_graph.json",
        )
        traces.append(trace)
        stage_outputs["merged_graph"] = graph

        learning_path, trace = self._run_stage(
            "plan",
            lambda: self._stage_plan(graph),
            input_summary=(
                f"{len(graph.get('nodes', []))} graph nodes, "
                f"{len(graph.get('edges', []))} graph edges"
            ),
            artifact_path=run_dir / "learning_path.json",
        )
        traces.append(trace)
        stage_outputs["learning_path"] = learning_path

        validation, trace = self._run_stage(
            "validate",
            lambda: self._stage_validate(metadata, transcript, graph, learning_path),
            input_summary="raw_transcript + merged_graph + learning_path",
            artifact_path=run_dir / "validation_report.json",
        )
        traces.append(trace)
        stage_outputs["validation_report"] = validation

        pipeline_trace = {
            "pipeline_version": PIPELINE_VERSION,
            "run_id": run_id,
            "generated_at": _utc_now(),
            "artifact_dir": str(run_dir),
            "datasource": metadata.get("datasource"),
            "transcript_source": transcript.get("source"),
            "stages": [trace.to_dict() for trace in traces],
        }
        _write_json(run_dir / "pipeline_trace.json", pipeline_trace)

        summary = self._build_summary(metadata, transcript, graph, learning_path, validation, traces)
        _write_json(run_dir / "summary.json", summary)

        result = {
            "run_id": run_id,
            "artifact_dir": str(run_dir),
            "summary": summary,
            "pipeline_trace": pipeline_trace,
            **stage_outputs,
        }
        logger.info(
            "Harness pipeline completed: run_id=%s, nodes=%s, claims=%s, passed=%s",
            run_id,
            summary["stats"]["node_count"],
            summary["stats"]["claim_count"],
            validation["passed"],
        )
        return result

    def _run_stage(
        self,
        name: str,
        fn,
        input_summary: str,
        artifact_path: Optional[Path] = None,
    ) -> tuple[Any, StageTrace]:
        started = time.perf_counter()
        warnings: list[str] = []
        status = "completed"
        try:
            data = fn()
            if isinstance(data, dict):
                warnings.extend(data.pop("_warnings", []))
            if artifact_path:
                _write_json(artifact_path, data)
            output_summary = self._summarize_stage(name, data)
        except Exception as exc:
            status = "failed"
            data = {
                "stage": name,
                "error": str(exc),
                "generated_at": _utc_now(),
            }
            warnings.append(str(exc))
            if artifact_path:
                _write_json(artifact_path, data)
            output_summary = f"failed: {exc}"
        duration_ms = int((time.perf_counter() - started) * 1000)
        return data, StageTrace(
            name=name,
            status=status,
            duration_ms=duration_ms,
            input_summary=input_summary,
            output_summary=output_summary,
            warnings=warnings,
            artifact=str(artifact_path) if artifact_path else None,
        )

    def _stage_ingest(self, bvid: str, datasource: str) -> dict[str, Any]:
        warnings = []
        if datasource != "sample":
            warnings.append(
                f"datasource={datasource} is not used by offline demo; falling back to sample adapter"
            )
        video = self.sample_tool.load_video(bvid)
        video.update({
            "stage": "ingest",
            "pipeline_version": PIPELINE_VERSION,
            "datasource": "sample" if datasource != "real" else "sample_fallback",
            "tool_calls": [
                {
                    "tool": "SampleHarnessTool.load_video",
                    "purpose": "read stable local video metadata for demo mode",
                    "source": "demo/sample_videos.json",
                }
            ],
            "fallback_used": datasource != "sample",
            "generated_at": _utc_now(),
            "_warnings": warnings,
        })
        return video

    def _stage_transcript(self, metadata: dict[str, Any], transcript_source: str) -> dict[str, Any]:
        warnings = []
        if transcript_source != "sample":
            warnings.append(
                f"transcript_source={transcript_source} unavailable in offline demo; using sample transcript"
            )
        transcript = self.sample_tool.load_transcript(metadata["bvid"])
        segments = []
        for i, segment in enumerate(transcript.get("segments", [])):
            start = float(segment.get("start_time") or 0)
            end = float(segment.get("end_time") or start)
            text = (segment.get("raw_text") or "").strip()
            if not text:
                warnings.append(f"segment {i} has empty text and was kept for validation")
            segments.append({
                "segment_index": int(segment.get("segment_index", i)),
                "start_time": start,
                "end_time": end,
                "raw_text": text,
                "source_type": segment.get("source_type", "sample_transcript"),
                "confidence": float(segment.get("confidence", 0.9)),
            })

        if not segments:
            warnings.append("transcript empty; generated metadata-summary fallback segment")
            segments = [{
                "segment_index": 0,
                "start_time": 0.0,
                "end_time": float(metadata.get("duration") or 60),
                "raw_text": f"视频标题：{metadata.get('title', metadata['bvid'])}",
                "source_type": "metadata_summary",
                "confidence": 0.3,
            }]

        return {
            "stage": "transcript",
            "bvid": metadata["bvid"],
            "title": metadata.get("title", ""),
            "source": "sample" if transcript_source != "real" else "sample_fallback",
            "tool_calls": [
                {
                    "tool": "SampleHarnessTool.load_transcript",
                    "purpose": "load timestamped transcript segments",
                    "source": f"demo/sample_transcripts/{metadata['bvid']}.json",
                }
            ],
            "segments": segments,
            "generated_at": _utc_now(),
            "_warnings": warnings,
        }

    def _stage_extract(self, metadata: dict[str, Any], transcript: dict[str, Any]) -> dict[str, Any]:
        concept_candidates: list[dict[str, Any]] = []
        claim_candidates: list[dict[str, Any]] = []
        prerequisite_candidates: list[dict[str, Any]] = []

        for segment in transcript.get("segments", []):
            extracted = self._extract_segment_rules(segment)
            for concept in extracted["concepts"]:
                concept_candidates.append({
                    **concept,
                    "bvid": metadata["bvid"],
                    "segment_index": segment["segment_index"],
                    "start_time": segment["start_time"],
                    "end_time": segment["end_time"],
                })
            for claim in extracted["claims"]:
                claim_candidates.append({
                    **claim,
                    "bvid": metadata["bvid"],
                    "segment_index": segment["segment_index"],
                    "start_time": segment["start_time"],
                    "end_time": segment["end_time"],
                    "raw_text": segment["raw_text"],
                })
            for target in extracted["targets"]:
                for prereq in extracted["prerequisites"]:
                    if _normalize_name(prereq) != _normalize_name(target):
                        prerequisite_candidates.append({
                            "source": prereq,
                            "target": target,
                            "type": "prerequisite_of",
                            "confidence": 0.68,
                            "segment_index": segment["segment_index"],
                        })

        return {
            "stage": "extract",
            "mode": "rules_with_agent_contract",
            "prompt_contract": "prompts/extract_knowledge.md",
            "context_policy": "one timestamped segment per extraction call",
            "concept_candidates": concept_candidates,
            "claim_candidates": claim_candidates,
            "prerequisite_candidates": prerequisite_candidates,
            "generated_at": _utc_now(),
        }

    def _extract_segment_rules(self, segment: dict[str, Any]) -> dict[str, Any]:
        text = segment["raw_text"]
        specs = [
            {
                "name": "Harness Engineering",
                "keys": ["Harness Engineering", "Harness"],
                "definition": "把 AI 能力封装进可观测、可验证、可回放工作流的工程方法。",
                "difficulty": 3,
                "prerequisites": ["Agent 工作流"],
            },
            {
                "name": "Agent 工作流",
                "keys": ["工作流", "Agent", "阶段", "pipeline"],
                "definition": "把复杂 AI 任务拆成多个有输入输出契约的执行阶段。",
                "difficulty": 2,
                "prerequisites": [],
            },
            {
                "name": "上下文管理",
                "keys": ["上下文管理", "上下文", "切块", "长文本"],
                "definition": "控制每个阶段读取的信息范围，减少长文本噪声和模型幻觉。",
                "difficulty": 3,
                "prerequisites": ["Agent 工作流"],
            },
            {
                "name": "外部工具调用",
                "keys": ["外部工具", "B 站接口", "字幕", "ASR", "工具层"],
                "definition": "通过 API、CLI 或本地文件获取真实数据，让模型输出有来源。",
                "difficulty": 3,
                "prerequisites": ["Agent 工作流"],
            },
            {
                "name": "验证反馈闭环",
                "keys": ["验证", "校验", "反馈闭环", "非法时间戳", "低置信度"],
                "definition": "对 AI 结构化输出做自动检查、标记、回退或修复。",
                "difficulty": 4,
                "prerequisites": ["上下文管理", "外部工具调用"],
            },
            {
                "name": "证据时间点回链",
                "keys": ["时间点", "证据链", "证据", "跳回原视频", "可追溯"],
                "definition": "把知识节点和论断连接回原视频的具体时间片段。",
                "difficulty": 2,
                "prerequisites": ["外部工具调用"],
            },
            {
                "name": "学习路径生成",
                "keys": ["学习路径", "先看什么", "依赖关系", "推荐"],
                "definition": "根据前置关系、难度和证据覆盖生成可执行学习顺序。",
                "difficulty": 3,
                "prerequisites": ["知识树构建"],
            },
            {
                "name": "知识树构建",
                "keys": ["知识树", "图谱", "知识图", "归并", "去重"],
                "definition": "把视频片段中的概念归并成可浏览的层级知识结构。",
                "difficulty": 3,
                "prerequisites": ["上下文管理"],
            },
        ]

        concepts = []
        claims = []
        prereqs = []
        targets = []
        for spec in specs:
            if any(key in text for key in spec["keys"]):
                confidence = 0.78 + min(0.15, text.count(spec["name"]) * 0.03)
                concepts.append({
                    "name": spec["name"],
                    "normalized_name": _normalize_name(spec["name"]),
                    "definition": spec["definition"],
                    "difficulty": spec["difficulty"],
                    "confidence": round(confidence, 2),
                })
                claims.append({
                    "concept": spec["name"],
                    "statement": self._claim_from_text(spec["name"], text),
                    "type": "explanation",
                    "confidence": round(confidence - 0.05, 2),
                    "evidence_segment_index": segment["segment_index"],
                })
                prereqs.extend(spec["prerequisites"])
                targets.append(spec["name"])

        return {
            "concepts": concepts[:5],
            "claims": claims[:8],
            "prerequisites": list(dict.fromkeys(prereqs)),
            "targets": targets,
        }

    def _claim_from_text(self, concept: str, text: str) -> str:
        sentences = re.split(r"[。！？!?]\s*", text)
        for sentence in sentences:
            if concept in sentence:
                return sentence.strip()[:160]
        return text.strip()[:160]

    def _stage_merge(
        self,
        metadata: dict[str, Any],
        extracted: dict[str, Any],
    ) -> dict[str, Any]:
        concept_map: dict[str, dict[str, Any]] = {}
        for candidate in extracted.get("concept_candidates", []):
            norm = candidate["normalized_name"]
            existing = concept_map.get(norm)
            if existing:
                existing["source_count"] += 1
                existing["confidence"] = max(existing["confidence"], candidate["confidence"])
                existing["difficulty"] = max(existing["difficulty"], candidate["difficulty"])
                existing["aliases"] = sorted(set(existing["aliases"] + [candidate["name"]]))
            else:
                concept_map[norm] = {
                    "id": f"n{len(concept_map) + 1}",
                    "name": candidate["name"],
                    "normalized_name": norm,
                    "aliases": [candidate["name"]],
                    "definition": candidate.get("definition", ""),
                    "difficulty": candidate.get("difficulty", 1),
                    "confidence": candidate.get("confidence", 0.5),
                    "source_count": 1,
                    "review_status": "verified",
                }

        claims = []
        evidence_links = []
        for idx, claim in enumerate(extracted.get("claim_candidates", []), start=1):
            norm = _normalize_name(claim["concept"])
            node = concept_map.get(norm)
            if not node:
                continue
            claim_id = f"c{idx}"
            claims.append({
                "id": claim_id,
                "node_id": node["id"],
                "concept": node["name"],
                "statement": claim["statement"],
                "type": claim["type"],
                "confidence": claim["confidence"],
                "segment_index": claim["segment_index"],
                "time": f"{_fmt_time(claim['start_time'])}-{_fmt_time(claim['end_time'])}",
                "start_time": claim["start_time"],
                "end_time": claim["end_time"],
                "raw_text": claim["raw_text"],
            })
            evidence_links.append({
                "id": f"e{idx}",
                "node_id": node["id"],
                "claim_id": claim_id,
                "bvid": metadata["bvid"],
                "segment_index": claim["segment_index"],
                "start_time": claim["start_time"],
                "end_time": claim["end_time"],
                "time": f"{_fmt_time(claim['start_time'])}-{_fmt_time(claim['end_time'])}",
                "confidence": claim["confidence"],
            })

        for node in concept_map.values():
            linked = [e for e in evidence_links if e["node_id"] == node["id"]]
            if node["confidence"] < 0.72 or len(linked) <= 1:
                node["review_status"] = "needs_review"

        edges = []
        edge_seen = set()
        for rel in extracted.get("prerequisite_candidates", []):
            src = concept_map.get(_normalize_name(rel["source"]))
            tgt = concept_map.get(_normalize_name(rel["target"]))
            if not src or not tgt or src["id"] == tgt["id"]:
                continue
            key = (src["id"], tgt["id"], rel["type"])
            if key in edge_seen:
                continue
            edge_seen.add(key)
            edges.append({
                "source": src["id"],
                "target": tgt["id"],
                "type": rel["type"],
                "confidence": rel["confidence"],
            })

        return {
            "stage": "merge",
            "prompt_contract": "prompts/build_graph.md",
            "video": {
                "bvid": metadata["bvid"],
                "title": metadata.get("title", ""),
                "duration": metadata.get("duration"),
                "source_url": metadata.get("source_url"),
            },
            "nodes": list(concept_map.values()),
            "claims": claims,
            "edges": edges,
            "evidence_links": evidence_links,
            "generated_at": _utc_now(),
        }

    def _stage_graph(
        self,
        metadata: dict[str, Any],
        transcript: dict[str, Any],
        merged: dict[str, Any],
    ) -> dict[str, Any]:
        """Build the graph artifact consumed by planning and UI stages."""
        graph = dict(merged)
        graph["stage"] = "graph"
        graph["graph_contract"] = "nodes + edges + evidence_links must be internally consistent"
        graph["transcript_segments"] = [
            {
                "segment_index": s["segment_index"],
                "start_time": s["start_time"],
                "end_time": s["end_time"],
                "source_type": s["source_type"],
                "confidence": s["confidence"],
            }
            for s in transcript.get("segments", [])
        ]
        graph["projection"] = {
            "root": metadata.get("title", metadata.get("bvid", "")),
            "node_count": len(graph.get("nodes", [])),
            "edge_count": len(graph.get("edges", [])),
            "evidence_count": len(graph.get("evidence_links", [])),
        }
        graph["generated_at"] = _utc_now()
        return graph

    def _stage_plan(self, graph: dict[str, Any]) -> dict[str, Any]:
        nodes = {node["id"]: node for node in graph.get("nodes", [])}
        incoming: dict[str, set[str]] = {nid: set() for nid in nodes}
        outgoing: dict[str, set[str]] = {nid: set() for nid in nodes}
        for edge in graph.get("edges", []):
            if edge["type"] != "prerequisite_of":
                continue
            if edge["source"] in nodes and edge["target"] in nodes:
                outgoing[edge["source"]].add(edge["target"])
                incoming[edge["target"]].add(edge["source"])

        ready = sorted(
            [nid for nid, prereqs in incoming.items() if not prereqs],
            key=lambda nid: (nodes[nid].get("difficulty", 1), -nodes[nid].get("source_count", 0), nodes[nid]["name"]),
        )
        ordered = []
        incoming_copy = {nid: set(vals) for nid, vals in incoming.items()}
        while ready:
            nid = ready.pop(0)
            if nid in ordered:
                continue
            ordered.append(nid)
            for target in sorted(outgoing.get(nid, [])):
                incoming_copy[target].discard(nid)
                if not incoming_copy[target] and target not in ordered and target not in ready:
                    ready.append(target)
            ready.sort(key=lambda item: (nodes[item].get("difficulty", 1), nodes[item]["name"]))

        remaining = [nid for nid in nodes if nid not in ordered]
        ordered.extend(sorted(remaining, key=lambda nid: (nodes[nid].get("difficulty", 1), nodes[nid]["name"])))

        evidence_by_node: dict[str, list[dict[str, Any]]] = {}
        for evidence in graph.get("evidence_links", []):
            evidence_by_node.setdefault(evidence["node_id"], []).append(evidence)

        steps = []
        for order, nid in enumerate(ordered, start=1):
            node = nodes[nid]
            prereq_names = [nodes[p]["name"] for p in sorted(incoming.get(nid, [])) if p in nodes]
            evidence_refs = [e["id"] for e in evidence_by_node.get(nid, [])[:2]]
            reason = "先学习基础概念" if not prereq_names else f"需要先理解：{', '.join(prereq_names)}"
            if node["review_status"] == "needs_review":
                reason += "；该节点证据较少，建议人工确认。"
            steps.append({
                "order": order,
                "node_id": nid,
                "title": node["name"],
                "reason": reason,
                "difficulty": node.get("difficulty", 1),
                "evidence_refs": evidence_refs,
                "status": node["review_status"],
            })

        return {
            "stage": "plan",
            "prompt_contract": "prompts/plan_learning_path.md",
            "target": graph.get("video", {}).get("title", ""),
            "mode": "standard",
            "steps": steps,
            "total_steps": len(steps),
            "generated_at": _utc_now(),
        }

    def _stage_validate(
        self,
        metadata: dict[str, Any],
        transcript: dict[str, Any],
        graph: dict[str, Any],
        learning_path: dict[str, Any],
    ) -> dict[str, Any]:
        errors: list[dict[str, str]] = []
        warnings: list[dict[str, str]] = []

        segments = transcript.get("segments", [])
        segment_by_index = {s.get("segment_index"): s for s in segments}
        if not metadata.get("bvid"):
            errors.append({"code": "missing_bvid", "message": "metadata.bvid is required"})
        if not segments:
            errors.append({"code": "empty_transcript", "message": "transcript has no segments"})

        nodes = graph.get("nodes", [])
        node_ids = {n.get("id") for n in nodes}
        normalized_names = [n.get("normalized_name") for n in nodes]
        duplicates = sorted({name for name in normalized_names if normalized_names.count(name) > 1})
        for name in duplicates:
            errors.append({"code": "duplicate_node", "message": f"duplicate normalized name: {name}"})

        evidence_by_node: dict[str, list[dict[str, Any]]] = {}
        for evidence in graph.get("evidence_links", []):
            evidence_by_node.setdefault(evidence.get("node_id"), []).append(evidence)
            if evidence.get("node_id") not in node_ids:
                errors.append({"code": "broken_evidence_node", "message": f"missing node {evidence.get('node_id')}"})
            segment = segment_by_index.get(evidence.get("segment_index"))
            if not segment:
                errors.append({"code": "missing_evidence_segment", "message": f"segment {evidence.get('segment_index')} not found"})
                continue
            start = evidence.get("start_time")
            end = evidence.get("end_time")
            if start is None or end is None or start < 0 or end <= start:
                errors.append({"code": "invalid_timestamp", "message": f"invalid evidence range for {evidence.get('id')}"})
            if end and segment.get("end_time") and end > segment["end_time"] + 1:
                warnings.append({"code": "timestamp_outside_segment", "message": f"evidence {evidence.get('id')} exceeds segment end"})

        for node in nodes:
            node_evidence = evidence_by_node.get(node.get("id"), [])
            if not node_evidence:
                warnings.append({"code": "node_missing_evidence", "message": f"{node.get('name')} has no evidence link"})
            if node.get("review_status") == "needs_review":
                warnings.append({"code": "low_confidence_node", "message": f"{node.get('name')} needs review"})

        for edge in graph.get("edges", []):
            if edge.get("source") not in node_ids or edge.get("target") not in node_ids:
                errors.append({"code": "broken_edge", "message": f"edge points to missing node: {edge}"})

        path_node_ids = [step.get("node_id") for step in learning_path.get("steps", [])]
        if len(path_node_ids) != len(set(path_node_ids)):
            errors.append({"code": "learning_path_cycle_or_duplicate", "message": "learning path repeats node ids"})
        for node_id in path_node_ids:
            if node_id not in node_ids:
                errors.append({"code": "broken_path_step", "message": f"path step points to missing node {node_id}"})

        checks = [
            {"name": "metadata_has_bvid", "passed": bool(metadata.get("bvid"))},
            {"name": "transcript_has_segments", "passed": bool(segments)},
            {"name": "deduplicated_node_names", "passed": not duplicates},
            {"name": "edges_reference_existing_nodes", "passed": not any(e["code"] == "broken_edge" for e in errors)},
            {"name": "evidence_timestamps_valid", "passed": not any(e["code"] == "invalid_timestamp" for e in errors)},
            {"name": "learning_path_references_existing_nodes", "passed": not any(e["code"] == "broken_path_step" for e in errors)},
        ]

        return {
            "stage": "validate",
            "passed": len(errors) == 0,
            "checks": checks,
            "errors": errors,
            "warnings": warnings,
            "summary": {
                "error_count": len(errors),
                "warning_count": len(warnings),
                "low_confidence_nodes": sum(1 for n in nodes if n.get("review_status") == "needs_review"),
                "validated_evidence_links": len(graph.get("evidence_links", [])),
            },
            "generated_at": _utc_now(),
        }

    def _build_summary(
        self,
        metadata: dict[str, Any],
        transcript: dict[str, Any],
        graph: dict[str, Any],
        learning_path: dict[str, Any],
        validation: dict[str, Any],
        traces: list[StageTrace],
    ) -> dict[str, Any]:
        return {
            "video": {
                "bvid": metadata.get("bvid"),
                "title": metadata.get("title"),
                "duration": metadata.get("duration"),
                "source_url": metadata.get("source_url"),
            },
            "stats": {
                "segment_count": len(transcript.get("segments", [])),
                "node_count": len(graph.get("nodes", [])),
                "claim_count": len(graph.get("claims", [])),
                "edge_count": len(graph.get("edges", [])),
                "evidence_count": len(graph.get("evidence_links", [])),
                "learning_step_count": len(learning_path.get("steps", [])),
                "validation_warning_count": validation.get("summary", {}).get("warning_count", 0),
            },
            "harness": {
                "pipeline_version": PIPELINE_VERSION,
                "datasource": metadata.get("datasource"),
                "transcript_source": transcript.get("source"),
                "validation_passed": validation.get("passed", False),
                "stage_count": len(traces),
                "stages": [trace.to_dict() for trace in traces],
            },
            "generated_at": _utc_now(),
        }

    def _summarize_stage(self, name: str, data: Any) -> str:
        if not isinstance(data, dict):
            return "non-dict artifact"
        if name == "ingest":
            return f"metadata for {data.get('bvid')} from {data.get('datasource')}"
        if name == "transcript":
            return f"{len(data.get('segments', []))} transcript segments"
        if name == "extract":
            return (
                f"{len(data.get('concept_candidates', []))} concepts, "
                f"{len(data.get('claim_candidates', []))} claims"
            )
        if name == "merge":
            return (
                f"{len(data.get('nodes', []))} deduped nodes, "
                f"{len(data.get('claims', []))} grounded claims"
            )
        if name == "graph":
            return (
                f"{len(data.get('nodes', []))} nodes, "
                f"{len(data.get('edges', []))} edges, "
                f"{len(data.get('evidence_links', []))} evidence links"
            )
        if name == "plan":
            return f"{len(data.get('steps', []))} learning steps"
        if name == "validate":
            return (
                f"passed={data.get('passed')}, "
                f"errors={len(data.get('errors', []))}, "
                f"warnings={len(data.get('warnings', []))}"
            )
        return "completed"


def load_latest_summary(output_root: str | Path = "artifacts/harness") -> Optional[dict[str, Any]]:
    root = Path(output_root)
    if not root.is_absolute():
        root = _repo_root() / root
    if not root.exists():
        return None
    runs = [p for p in root.iterdir() if p.is_dir()]
    if not runs:
        return None
    latest = max(runs, key=lambda p: p.stat().st_mtime)
    summary_path = latest / "summary.json"
    if not summary_path.exists():
        return None
    return _read_json(summary_path)
