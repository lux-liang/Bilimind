"""
Weakly-supervised video organizer classifier.

任务：
1. primary_subject
2. content_type
3. difficulty_level
4. value_tier
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from app.config import settings
from app.services.lightweight_models import HashedMulticlassOVRModel


def _tokenize(text: str) -> list[str]:
    tokens = re.findall(r"[a-zA-Z0-9\u4e00-\u9fff]+", text.lower())
    return [token for token in tokens if len(token) > 1]


@dataclass
class OrganizerVideoSample:
    title: str
    description: str
    summary: str
    folder_titles: list[str]
    tags: list[str]
    knowledge_node_count: int
    claim_count: int
    segment_count: int
    avg_node_difficulty: float
    node_confidence_avg: float
    duration: int


def build_video_classifier_features(video: OrganizerVideoSample) -> tuple[dict[str, float], list[str]]:
    text_blob = " ".join([
        video.title,
        video.description,
        video.summary,
        " ".join(video.folder_titles),
        " ".join(video.tags),
    ])
    tokens = _tokenize(text_blob)
    numeric = {
        "knowledge_node_count": float(video.knowledge_node_count),
        "claim_count": float(video.claim_count),
        "segment_count": float(video.segment_count),
        "avg_node_difficulty": float(video.avg_node_difficulty),
        "node_confidence_avg": float(video.node_confidence_avg),
        "duration_bucket": min(8.0, float(video.duration or 0) / 300.0),
    }
    token_features = [f"tok::{token}" for token in tokens[:48]]
    token_features.extend(f"folder::{token}" for title in video.folder_titles for token in _tokenize(title)[:8])
    token_features.extend(f"tag::{token}" for token in video.tags[:8])
    return numeric, token_features


class OrganizerClassifierBundle:
    def __init__(self, tasks: Optional[dict[str, HashedMulticlassOVRModel]] = None):
        self.tasks = tasks or {}

    def predict(self, video: OrganizerVideoSample) -> dict[str, dict]:
        numeric, tokens = build_video_classifier_features(video)
        outputs: dict[str, dict] = {}
        for task, model in self.tasks.items():
            label, confidence, scores = model.predict(numeric, tokens)
            outputs[task] = {
                "label": label,
                "confidence": round(confidence, 4),
                "scores": {key: round(value, 4) for key, value in scores.items()},
            }
        return outputs

    def to_dict(self) -> dict:
        return {
            "tasks": {name: model.to_dict() for name, model in self.tasks.items()},
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "OrganizerClassifierBundle":
        tasks = {
            name: HashedMulticlassOVRModel.from_dict(model_payload)
            for name, model_payload in (payload.get("tasks") or {}).items()
        }
        return cls(tasks=tasks)

    def save(self, path: str | Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "OrganizerClassifierBundle":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls.from_dict(payload)


class OrganizerClassifierService:
    def __init__(self, model_path: Optional[str] = None):
        self.model_path = Path(model_path or settings.organizer_classifier_model_path)
        self.bundle = self._try_load()

    def _try_load(self) -> Optional[OrganizerClassifierBundle]:
        if not settings.organizer_classifier_enabled or not self.model_path.exists():
            return None
        try:
            return OrganizerClassifierBundle.load(self.model_path)
        except Exception:
            return None

    @property
    def is_enabled(self) -> bool:
        return self.bundle is not None

    def predict(self, video: OrganizerVideoSample) -> dict[str, dict]:
        if not self.bundle:
            return {}
        return self.bundle.predict(video)
