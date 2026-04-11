"""
构造知识点-视频片段相关性判别器训练数据。

输出 schema:
{
  "sample_id": "node-12-seg-34-pos",
  "query_id": "node-12-seg-34",
  "split": "train|val|test",
  "label": 1,
  "node_id": 12,
  "node_name": "...",
  "node_definition": "...",
  "node_type": "concept",
  "node_aliases": ["..."],
  "node_confidence": 0.82,
  "node_source_count": 3,
  "video_id": "BV...",
  "video_title": "...",
  "segment_id": 34,
  "segment_text": "...",
  "segment_source_type": "subtitle",
  "segment_confidence": 1.0,
  "knowledge_density": 0.4,
  "is_peak": false,
  "relation": "explains",
  "link_confidence": 0.9,
  "rule_score": 0.88,
  "negative_kind": "random|same_video|hard_negative|none",
  "numeric_features": {...},
  "token_features": [...]
}
"""
from __future__ import annotations

import argparse
import json
import random
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace
import re

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402
from app.services.evidence_ranker import build_features_from_record, rule_score_segment_match  # noqa: E402


def _normalize_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def _tokenize(value: str | None) -> list[str]:
    tokens = re.findall(r"[a-zA-Z0-9\u4e00-\u9fff]+", (value or "").lower())
    return [token for token in tokens if len(token) > 1]


def _jaccard(left: list[str], right: list[str]) -> float:
    a, b = set(left), set(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _make_pseudo_link(confidence: float = 0.0, relation: str = "unknown") -> SimpleNamespace:
    return SimpleNamespace(confidence=confidence, relation=relation)


def _segment_text(seg: SimpleNamespace) -> str:
    return seg.cleaned_text or seg.raw_text or ""


def _node_text(node: SimpleNamespace) -> str:
    aliases = node.aliases or []
    return " ".join([node.name, node.definition or "", *aliases]).strip()


def _candidate_overlap(node: SimpleNamespace, segment: SimpleNamespace, video: SimpleNamespace | None) -> dict[str, float]:
    node_tokens = _tokenize(_node_text(node))
    seg_tokens = _tokenize(_segment_text(segment))
    title_tokens = _tokenize(video.title if video else "")
    return {
        "segment_overlap": _jaccard(node_tokens, seg_tokens),
        "title_overlap": _jaccard(node_tokens, title_tokens),
    }


def _negative_priority(
    node: SimpleNamespace,
    segment: SimpleNamespace,
    video: SimpleNamespace | None,
) -> tuple[float, float]:
    overlap = _candidate_overlap(node, segment, video)
    pseudo_link = _make_pseudo_link()
    rule_score = rule_score_segment_match(node, pseudo_link, segment, video)
    if (segment.source_type or "") == "basic":
        rule_score += 0.04
    return rule_score, overlap["segment_overlap"] + overlap["title_overlap"]


def assign_split(video_id: str) -> str:
    value = sum(video_id.encode("utf-8")) % 10
    if value < 7:
        return "train"
    if value < 9:
        return "val"
    return "test"


def make_record(
    *,
    query_id: str,
    split: str,
    label: int,
    negative_kind: str,
    node: KnowledgeNode,
    segment: Segment,
    video: VideoCache | None,
    relation: str,
    link_confidence: float,
    rule_score: float,
) -> dict:
    overlap = _candidate_overlap(node, segment, video)
    record = {
        "sample_id": f"{query_id}-{'pos' if label else negative_kind}-{segment.id}",
        "query_id": query_id,
        "split": split,
        "label": label,
        "node_id": node.id,
        "node_name": node.name,
        "node_definition": node.definition or "",
        "node_type": node.node_type,
        "node_aliases": node.aliases or [],
        "node_confidence": float(node.confidence or 0.0),
        "node_source_count": int(node.source_count or 0),
        "video_id": segment.video_bvid,
        "video_title": video.title if video else "",
        "segment_id": segment.id,
        "segment_text": segment.cleaned_text or segment.raw_text or "",
        "segment_source_type": segment.source_type or "",
        "segment_confidence": float(segment.confidence or 0.0),
        "knowledge_density": float(segment.knowledge_density or 0.0),
        "is_peak": bool(segment.is_peak),
        "relation": relation,
        "link_confidence": float(link_confidence),
        "rule_score": float(rule_score),
        "negative_kind": negative_kind,
        "segment_overlap": overlap["segment_overlap"],
        "title_overlap": overlap["title_overlap"],
    }
    numeric_features, token_features = build_features_from_record(record)
    numeric_features["link_confidence"] = float(link_confidence)
    numeric_features["rule_score"] = float(rule_score)
    record["numeric_features"] = numeric_features
    record["token_features"] = token_features
    return record


def resolve_sqlite_path(database_url: str) -> Path:
    prefix = "sqlite+aiosqlite:///"
    if database_url.startswith(prefix):
        raw = database_url[len(prefix):]
    elif database_url.startswith("sqlite:///"):
        raw = database_url[len("sqlite:///"):]
    else:
        raise ValueError(f"当前脚本仅支持 SQLite，收到: {database_url}")
    db_path = Path(raw)
    if not db_path.is_absolute():
        db_path = ROOT / db_path
    return db_path


def decode_json_field(value, fallback):
    if value in (None, ""):
        return fallback
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return fallback


def row_to_namespace(row: sqlite3.Row, json_fields: dict[str, object] | None = None) -> SimpleNamespace:
    payload = dict(row)
    for field, fallback in (json_fields or {}).items():
        payload[field] = decode_json_field(payload.get(field), fallback)
    return SimpleNamespace(**payload)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default=str(ROOT / "data" / "training" / "evidence_ranker"))
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--max-negatives-per-positive", type=int, default=4)
    parser.add_argument("--min-positive-rule-score", type=float, default=0.45)
    parser.add_argument("--session-id", default=None, help="仅导出指定 session_id 的样本，避免跨用户混合")
    args = parser.parse_args()

    random.seed(args.seed)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    db_path = resolve_sqlite_path(settings.database_url)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    session_clause = " WHERE session_id = ? " if args.session_id else ""
    params = [args.session_id] if args.session_id else []

    links = [
        row_to_namespace(row)
        for row in conn.execute(f"SELECT * FROM node_segment_links{session_clause}", params).fetchall()
    ]
    nodes = {
        item.id: item
        for item in [
            row_to_namespace(row, {"aliases": []})
            for row in conn.execute(f"SELECT * FROM knowledge_nodes{session_clause}", params).fetchall()
        ]
    }
    segments = {
        item.id: item
        for item in [
            row_to_namespace(row)
            for row in conn.execute(f"SELECT * FROM segments{session_clause}", params).fetchall()
        ]
    }
    videos = {
        item.bvid: item
        for item in [
            row_to_namespace(row, {"tags": []})
            for row in conn.execute("SELECT * FROM video_cache").fetchall()
        ]
    }
    conn.close()

    by_video: dict[str, list[SimpleNamespace]] = defaultdict(list)
    by_session: dict[str | None, list[SimpleNamespace]] = defaultdict(list)
    linked_segment_ids_by_node: dict[int, set[int]] = defaultdict(set)
    for seg in segments.values():
        by_video[seg.video_bvid].append(seg)
        by_session[getattr(seg, "session_id", None)].append(seg)
    for link in links:
        linked_segment_ids_by_node[int(link.node_id)].add(int(link.segment_id))

    all_rows: list[dict] = []
    for link in links:
        node = nodes.get(link.node_id)
        segment = segments.get(link.segment_id)
        if not node or not segment:
            continue
        video = videos.get(link.video_bvid or segment.video_bvid)
        pos_score = rule_score_segment_match(node, link, segment)
        if pos_score < args.min_positive_rule_score:
            continue

        query_id = f"node-{node.id}-seg-{segment.id}"
        split = assign_split(segment.video_bvid)
        all_rows.append(make_record(
            query_id=query_id,
            split=split,
            label=1,
            negative_kind="none",
            node=node,
            segment=segment,
            video=video,
            relation=link.relation or "mentions",
            link_confidence=float(link.confidence or 0.0),
            rule_score=pos_score,
        ))

        session_segments = by_session.get(getattr(segment, "session_id", None), [])
        linked_ids = linked_segment_ids_by_node.get(int(node.id), set())
        negatives: list[tuple[SimpleNamespace, str, float, float]] = []

        same_video_neighbors = [
            seg for seg in by_video.get(segment.video_bvid, [])
            if seg.id != segment.id
            and seg.id not in linked_ids
            and abs(int(seg.segment_index or 0) - int(segment.segment_index or 0)) <= 3
        ]
        same_video_neighbors.sort(
            key=lambda seg: _negative_priority(node, seg, videos.get(seg.video_bvid)),
            reverse=True,
        )
        negatives.extend(
            (seg, "same_video_neighbor", *_negative_priority(node, seg, videos.get(seg.video_bvid)))
            for seg in same_video_neighbors[:2]
        )

        lexical_hard = [
            seg for seg in session_segments
            if seg.id != segment.id
            and seg.id not in linked_ids
            and seg.video_bvid != segment.video_bvid
            and _negative_priority(node, seg, videos.get(seg.video_bvid))[1] > 0
        ]
        lexical_hard.sort(
            key=lambda seg: _negative_priority(node, seg, videos.get(seg.video_bvid)),
            reverse=True,
        )
        negatives.extend(
            (seg, "lexical_hard", *_negative_priority(node, seg, videos.get(seg.video_bvid)))
            for seg in lexical_hard[:2]
        )

        title_confusers = [
            seg for seg in session_segments
            if seg.id != segment.id
            and seg.id not in linked_ids
            and seg.video_bvid != segment.video_bvid
            and _candidate_overlap(node, seg, videos.get(seg.video_bvid))["title_overlap"] > 0
        ]
        title_confusers.sort(
            key=lambda seg: _negative_priority(node, seg, videos.get(seg.video_bvid)),
            reverse=True,
        )
        negatives.extend(
            (seg, "title_confuser", *_negative_priority(node, seg, videos.get(seg.video_bvid)))
            for seg in title_confusers[:1]
        )

        basic_confusers = [
            seg for seg in session_segments
            if seg.id != segment.id
            and seg.id not in linked_ids
            and (seg.source_type or "") == "basic"
        ]
        basic_confusers.sort(
            key=lambda seg: _negative_priority(node, seg, videos.get(seg.video_bvid)),
            reverse=True,
        )
        negatives.extend(
            (seg, "basic_confuser", *_negative_priority(node, seg, videos.get(seg.video_bvid)))
            for seg in basic_confusers[:1]
        )

        random_pool = [
            seg for seg in session_segments
            if seg.id != segment.id
            and seg.id not in linked_ids
            and seg.video_bvid != segment.video_bvid
        ]
        random.shuffle(random_pool)
        negatives.extend(
            (seg, "random", *_negative_priority(node, seg, videos.get(seg.video_bvid)))
            for seg in random_pool[:3]
        )

        seen_segments: set[int] = set()
        taken = 0
        negatives.sort(key=lambda item: (item[2], item[3]), reverse=True)
        for negative_segment, negative_kind, negative_rule_score, _priority in negatives:
            if negative_segment.id in seen_segments:
                continue
            seen_segments.add(negative_segment.id)
            taken += 1
            all_rows.append(make_record(
                query_id=query_id,
                split=split,
                label=0,
                negative_kind=negative_kind,
                node=node,
                segment=negative_segment,
                video=videos.get(negative_segment.video_bvid),
                relation="unknown",
                link_confidence=0.0,
                rule_score=negative_rule_score,
            ))
            if taken >= args.max_negatives_per_positive:
                break

    split_rows: dict[str, list[dict]] = {"train": [], "val": [], "test": []}
    for row in all_rows:
        split_rows[row["split"]].append(row)

    for split, rows in split_rows.items():
        path = output_dir / f"{split}.jsonl"
        with path.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    negative_kind_counts = defaultdict(int)
    for row in all_rows:
        if row["label"] == 0:
            negative_kind_counts[row["negative_kind"]] += 1

    summary = {
        split: {
            "rows": len(rows),
            "positives": sum(1 for row in rows if row["label"] == 1),
            "negatives": sum(1 for row in rows if row["label"] == 0),
            "queries": len({row["query_id"] for row in rows}),
        }
        for split, rows in split_rows.items()
    }
    summary["negative_kind_counts"] = dict(sorted(negative_kind_counts.items()))
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
