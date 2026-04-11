"""
Lightweight trainable models for competition delivery.

实现目标：
1. 不引入大型训练/推理依赖
2. 训练结果可保存为 JSON
3. 推理可直接嵌入后端服务
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional


def _stable_hash(name: str, buckets: int) -> int:
    digest = hashlib.md5(name.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % buckets


def _sigmoid(value: float) -> float:
    if value >= 0:
        z = math.exp(-value)
        return 1.0 / (1.0 + z)
    z = math.exp(value)
    return z / (1.0 + z)


@dataclass
class SparseSample:
    label: float
    numeric_features: dict[str, float]
    token_features: list[str]


class HashedBinaryLogisticModel:
    def __init__(
        self,
        buckets: int = 512,
        weights: Optional[list[float]] = None,
        bias: float = 0.0,
        metadata: Optional[dict] = None,
    ):
        self.buckets = buckets
        self.weights = weights[:] if weights is not None else [0.0] * buckets
        self.bias = float(bias)
        self.metadata = metadata or {}

    def _vectorize(self, numeric_features: dict[str, float], token_features: Iterable[str]) -> dict[int, float]:
        sparse: dict[int, float] = {}
        for key, value in numeric_features.items():
            idx = _stable_hash(f"num::{key}", self.buckets)
            sparse[idx] = sparse.get(idx, 0.0) + float(value)
        for token in token_features:
            idx = _stable_hash(f"tok::{token}", self.buckets)
            sparse[idx] = sparse.get(idx, 0.0) + 1.0
        return sparse

    def raw_score(self, numeric_features: dict[str, float], token_features: Iterable[str]) -> float:
        sparse = self._vectorize(numeric_features, token_features)
        score = self.bias
        for idx, value in sparse.items():
            score += self.weights[idx] * value
        return score

    def predict_proba(self, numeric_features: dict[str, float], token_features: Iterable[str]) -> float:
        return _sigmoid(self.raw_score(numeric_features, token_features))

    def fit(
        self,
        samples: list[SparseSample],
        epochs: int = 8,
        lr: float = 0.08,
        l2: float = 1e-4,
        positive_weight: float = 1.0,
    ) -> None:
        if not samples:
            return
        for _ in range(max(1, epochs)):
            for sample in samples:
                sparse = self._vectorize(sample.numeric_features, sample.token_features)
                raw = self.bias
                for idx, value in sparse.items():
                    raw += self.weights[idx] * value
                pred = _sigmoid(raw)
                error = pred - sample.label
                if sample.label > 0.5:
                    error *= positive_weight
                self.bias -= lr * error
                for idx, value in sparse.items():
                    grad = error * value + l2 * self.weights[idx]
                    self.weights[idx] -= lr * grad

    def to_dict(self) -> dict:
        return {
            "type": "binary_logistic",
            "buckets": self.buckets,
            "weights": self.weights,
            "bias": self.bias,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "HashedBinaryLogisticModel":
        return cls(
            buckets=int(payload.get("buckets", 512)),
            weights=[float(v) for v in payload.get("weights", [])],
            bias=float(payload.get("bias", 0.0)),
            metadata=payload.get("metadata") or {},
        )

    def save(self, path: str | Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "HashedBinaryLogisticModel":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls.from_dict(payload)


class HashedMulticlassOVRModel:
    def __init__(self, labels: list[str], buckets: int = 512):
        self.labels = labels[:]
        self.buckets = buckets
        self.models = {
            label: HashedBinaryLogisticModel(buckets=buckets, metadata={"label": label})
            for label in self.labels
        }

    def fit(
        self,
        dataset: list[tuple[str, dict[str, float], list[str]]],
        epochs: int = 8,
        lr: float = 0.08,
        l2: float = 1e-4,
    ) -> None:
        for label in self.labels:
            samples = [
                SparseSample(
                    label=1.0 if target == label else 0.0,
                    numeric_features=numeric,
                    token_features=tokens,
                )
                for target, numeric, tokens in dataset
            ]
            positives = sum(1 for sample in samples if sample.label > 0.5)
            negatives = max(1, len(samples) - positives)
            positive_weight = max(1.0, negatives / max(1, positives))
            self.models[label].fit(samples, epochs=epochs, lr=lr, l2=l2, positive_weight=positive_weight)

    def predict(self, numeric_features: dict[str, float], token_features: list[str]) -> tuple[str, float, dict[str, float]]:
        scores = {
            label: model.predict_proba(numeric_features, token_features)
            for label, model in self.models.items()
        }
        best_label = max(scores.items(), key=lambda item: item[1])[0]
        return best_label, scores[best_label], scores

    def to_dict(self) -> dict:
        return {
            "type": "multiclass_ovr",
            "labels": self.labels,
            "buckets": self.buckets,
            "models": {label: model.to_dict() for label, model in self.models.items()},
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "HashedMulticlassOVRModel":
        model = cls(labels=list(payload.get("labels", [])), buckets=int(payload.get("buckets", 512)))
        model.models = {
            label: HashedBinaryLogisticModel.from_dict(model_payload)
            for label, model_payload in (payload.get("models") or {}).items()
        }
        return model

    def save(self, path: str | Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "HashedMulticlassOVRModel":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls.from_dict(payload)
