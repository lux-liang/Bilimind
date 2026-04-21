# BiliMind Harness Agent Skill

This skill defines how BiliMind turns messy saved videos into a verified
knowledge navigation artifact. It is intentionally stage-based: each stage
reads only the minimal context it needs, writes a JSON artifact, and exposes
deterministic checks before the next stage runs.

## Goal

Given a Bilibili video, favorite list export, URL list, or local sample data,
produce:

- Deduplicated knowledge nodes
- Evidence links back to transcript timestamps
- A dependency graph
- A learning path
- A validation report that flags low-confidence or broken outputs
- A render bundle that the frontend can display without hidden model state

## Context Budget Rules

- Never pass the full transcript to every stage.
- Split transcripts into timestamped chunks before extraction.
- Each extraction chunk should stay under roughly 1,200 Chinese characters or
  3,000 prompt characters.
- Merge only normalized concept candidates, claim summaries, and evidence IDs.
- Planning stages read graph summaries and evidence summaries, not raw full text.
- Validation reads all structured artifacts, but does not call the LLM.
- Render reads validated graph/evidence bundles only; it never re-reads raw
  transcript in full.

## Stage Contracts

### 1. ingest

Input:

- `demo/sample_videos.json` or a real Bilibili URL/favorite list.

Output:

- `raw_metadata.json`

Rules:

- Keep original IDs, source URL, title, owner, duration, and datasource.
- If the real API fails, fall back to sample data and mark `fallback_used=true`.

### 2. transcript

Input:

- Metadata with `bvid`
- Transcript source: `api`, `local`, `asr`, or `sample`

Output:

- `raw_transcript.json`

Rules:

- Every segment must have `segment_index`, `start_time`, `end_time`, `raw_text`,
  `source_type`, and `confidence`.
- Empty transcripts must be replaced with sample or metadata-summary mode and
  recorded as a warning.

### 3. extract

Input:

- One transcript segment at a time.

Output:

- `extracted_nodes.json`

Rules:

- Extract 1-5 concepts and 1-8 claims per segment.
- Every claim must cite the segment ID/time range.
- Drop broad/noisy concepts such as "video", "content", "learning", "thing".
- If LLM output is invalid JSON, use rule fallback.

### 4. merge

Input:

- Extracted concept candidates and claims.

Output:

- `merged_nodes.json`

Rules:

- Normalize names before merging.
- Preserve aliases and source counts.
- Prefer high-confidence definitions.
- Mark single-source or low-confidence nodes as `needs_review`.

### 5. graph

Input:

- Merged nodes, claims, prerequisites.

Output:

- `merged_graph.json`

Rules:

- Edges must point between existing node IDs.
- `prerequisite_of` means the source should be learned before the target.
- Evidence links must use valid transcript time ranges.

### 6. plan

Input:

- Graph summary, node difficulty, evidence counts.

Output:

- `learning_path.json`

Rules:

- Start with prerequisites and low difficulty nodes.
- Avoid cycles by tracking visited node IDs.
- Each step must include a reason and at least one evidence pointer when
  available.

### 7. evidence

Input:

- `merged_graph.json`
- `learning_path.json`
- segment-level transcript metadata

Output:

- `evidence_map.json`

Rules:

- Every evidence packet must preserve `node_id`, `claim_id`, `segment_index`,
  `start_time`, `end_time`, and a text preview.
- Learning path steps should be mapped to evidence packet IDs where available.
- If a step has no evidence, keep the step but mark it as uncovered for review.

### 8. validate

Input:

- All prior artifacts.

Output:

- `validation_report.json`

Rules:

- Check JSON structure.
- Check duplicate normalized names.
- Check missing evidence.
- Check timestamp ranges.
- Check graph edges and learning path cycles.
- Check learning-path-to-evidence references.
- Return `passed=false` if blocking errors exist; otherwise flag warnings.

### 9. render

Input:

- `merged_graph.json`
- `learning_path.json`
- `evidence_map.json`
- `validation_report.json`

Output:

- `render_bundle.json`

Rules:

- Render bundle must be derivable from prior artifacts with no hidden model
  memory.
- Include timeline density, concept cards, and a validation banner.
- If validation fails, render bundle may still exist for debugging/demo, but
  must preserve the failure state.

## Failure Strategy

- Tool/API failures should not stop the demo path.
- Prefer fallback artifacts with explicit warnings over empty UI states.
- Low confidence does not hide data; it marks nodes as `needs_review`.
- Validation is deterministic and runs without network access.
- Render is deterministic and must not silently repair validation failures.
