"""The ranker: three logistic heads and one value per candidate.

Heads (each P(label | features) from a logistic model over ``FEATURES``):

- ``open``: the listener opens the artist from the card;
- ``listen``: they press "Listen on YouTube Music";
- ``negative``: they press "not interested" or scroll past at once.

The value a card is ranked by is ``Σ utility[head] * P(head)``: listening
counts most, opening counts, and a likely "not interested" costs. Multi-task
heads like these are how large feeds balance engagement against annoyance.

``PRIOR`` is the hand-set model served before there is data: it encodes the
documented intuitions (agreement between sources, closeness to seeds, genre
fit, photos help, fatigue and negatives hurt). ``train`` fits each head on
logged impressions with L2-regularized logistic regression (full-batch Adam),
evaluates on a time-ordered holdout, and returns metrics the training job uses
to decide whether to promote the new model.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import cast

import numpy as np

from songnexus.core.metrics import roc_auc
from songnexus.core.zstar.features import FEATURES, vector

HEADS = ("open", "listen", "negative")
UTILITY = {"open": 1.0, "listen": 2.0, "negative": -1.5}
PRIOR_VERSION = "prior-1"

_PRIOR_WEIGHTS: dict[str, dict[str, float]] = {
    "open": {
        "bias": -2.6,
        "walk": 0.9,
        "colisten": 0.8,
        "embed": 0.7,
        "genre": 0.4,
        "friends": 0.6,
        "explore": 0.1,
        "sources": 1.2,
        "genre_affinity": 1.0,
        "genre_penalty": -1.5,
        "negative_similarity": -1.2,
        "seed_similarity": 1.0,
        "popularity": 0.5,
        "has_image": 0.6,
        "seen_before": -0.4,
        "opened_before": 0.3,
        "skip_rate": -1.0,
        "fatigue": -1.5,
    },
    "listen": {
        "bias": -3.6,
        "walk": 0.8,
        "colisten": 1.0,
        "embed": 0.6,
        "genre": 0.4,
        "friends": 0.5,
        "sources": 1.0,
        "genre_affinity": 1.0,
        "genre_penalty": -1.5,
        "negative_similarity": -1.2,
        "seed_similarity": 1.0,
        "popularity": 0.6,
        "has_image": 0.3,
        "opened_before": 0.6,
        "skip_rate": -1.0,
        "fatigue": -1.5,
    },
    "negative": {
        "bias": -3.0,
        "explore": 0.4,
        "genre_affinity": -1.0,
        "genre_penalty": 2.0,
        "negative_similarity": 2.5,
        "seed_similarity": -0.8,
        "novelty": 0.3,
        "skip_rate": 1.5,
        "fatigue": 1.0,
    },
}


@dataclass(frozen=True)
class Model:
    """A ranking model: weights per head over ``features``, plus provenance.

    Attributes:
        version: ``prior-1`` or ``trained-<timestamp>``.
        weights: Head -> feature -> weight.
        features: The column order the weights were trained with.
        metrics: Training metrics (holdout AUC per head, examples, positives).
    """

    version: str
    weights: Mapping[str, Mapping[str, float]]
    features: tuple[str, ...] = FEATURES
    metrics: Mapping[str, float] = field(default_factory=dict)

    def heads(self, features: Mapping[str, float]) -> dict[str, float]:
        """P(head) for one candidate."""
        out = {}
        for head in HEADS:
            w = self.weights.get(head, {})
            z = sum(w.get(name, 0.0) * features.get(name, 0.0) for name in self.features)
            out[head] = 1.0 / (1.0 + math.exp(-max(min(z, 30.0), -30.0)))
        return out

    def value(self, features: Mapping[str, float]) -> tuple[float, dict[str, float]]:
        """The ranking value and the head probabilities behind it."""
        heads = self.heads(features)
        return sum(UTILITY[h] * p for h, p in heads.items()), heads

    def to_payload(self) -> dict[str, object]:
        """JSON-safe form for storage."""
        return {
            "version": self.version,
            "features": list(self.features),
            "weights": {h: dict(w) for h, w in self.weights.items()},
            "metrics": dict(self.metrics),
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> Model:
        """Reads ``to_payload`` output."""
        weights = cast("Mapping[str, Mapping[str, float]]", payload["weights"])
        features = cast("Sequence[str]", payload.get("features", FEATURES))
        metrics = cast("Mapping[str, float]", payload.get("metrics", {}))
        return cls(
            version=str(payload["version"]),
            weights={str(h): {str(k): float(v) for k, v in w.items()} for h, w in weights.items()},
            features=tuple(str(f) for f in features),
            metrics={str(k): float(v) for k, v in metrics.items()},
        )


PRIOR = Model(version=PRIOR_VERSION, weights=_PRIOR_WEIGHTS)


@dataclass(frozen=True)
class Example:
    """One logged impression: the features served and what happened."""

    features: Mapping[str, float]
    labels: Mapping[str, bool]  # head -> happened


@dataclass(frozen=True)
class TrainConfig:
    """Training settings."""

    l2: float = 1e-3
    learning_rate: float = 0.05
    steps: int = 400
    holdout: float = 0.2
    min_examples: int = 500
    min_positives: int = 20


def _fit_head(x: np.ndarray, y: np.ndarray, start: np.ndarray, config: TrainConfig) -> np.ndarray:
    """L2 logistic regression by full-batch Adam, warm-started from ``start``."""
    w = start.astype(np.float64).copy()
    m = np.zeros_like(w)
    v = np.zeros_like(w)
    positives = max(float(y.sum()), 1.0)
    negatives = max(float(len(y) - y.sum()), 1.0)
    # Balance the classes so rare labels (listens) still pull the weights.
    sample_w = np.where(y > 0, len(y) / (2 * positives), len(y) / (2 * negatives))
    for t in range(1, config.steps + 1):
        z = np.clip(x @ w, -30, 30)
        p = 1.0 / (1.0 + np.exp(-z))
        grad = x.T @ ((p - y) * sample_w) / len(y) + config.l2 * w
        grad[0] -= config.l2 * w[0]  # no penalty on the bias
        m = 0.9 * m + 0.1 * grad
        v = 0.999 * v + 0.001 * grad * grad
        m_hat = m / (1 - 0.9**t)
        v_hat = v / (1 - 0.999**t)
        w -= config.learning_rate * m_hat / (np.sqrt(v_hat) + 1e-8)
    return w


def evaluate(model: Model, examples: Sequence[Example]) -> dict[str, float]:
    """Holdout AUC per head (heads without both classes are skipped)."""
    metrics: dict[str, float] = {}
    for head in HEADS:
        scored = [(model.heads(e.features)[head], e.labels.get(head, False)) for e in examples]
        auc = roc_auc([s for s, y in scored if y], [s for s, y in scored if not y])
        if auc is not None:
            metrics[f"auc_{head}"] = round(auc, 4)
    return metrics


def train(
    examples: Sequence[Example],
    version: str,
    start: Model = PRIOR,
    config: TrainConfig | None = None,
) -> Model | None:
    """Fits every head on time-ordered examples; None when there is too little data.

    The last ``holdout`` share is held out; the returned model's metrics report
    its holdout AUC per head next to the starting model's on the same examples
    (``baseline_auc_<head>``), so the caller can refuse a worse model.
    """
    config = config or TrainConfig()
    if len(examples) < config.min_examples:
        return None
    split = int(len(examples) * (1 - config.holdout))
    fit, hold = examples[:split], examples[split:]
    x = np.asarray([vector(e.features) for e in fit], dtype=np.float64)
    weights: dict[str, dict[str, float]] = {}
    for head in HEADS:
        y = np.asarray([1.0 if e.labels.get(head) else 0.0 for e in fit])
        start_w = np.asarray([start.weights.get(head, {}).get(n, 0.0) for n in FEATURES])
        if y.sum() < config.min_positives or y.sum() == len(y):
            weights[head] = dict(zip(FEATURES, start_w.tolist(), strict=True))
            continue
        w = _fit_head(x, y, start_w, config)
        weights[head] = {n: round(float(v), 5) for n, v in zip(FEATURES, w, strict=True)}
    model = Model(version=version, weights=weights)
    metrics = dict(evaluate(model, hold))
    for key, value in evaluate(start, hold).items():
        metrics[f"baseline_{key}"] = value
    metrics["examples"] = float(len(examples))
    for head in HEADS:
        metrics[f"positives_{head}"] = float(sum(1 for e in examples if e.labels.get(head)))
    return Model(version=version, weights=weights, metrics=metrics)


def better(candidate: Model, tolerance: float = 0.005) -> bool:
    """Whether a trained model is no worse than its baseline on every evaluated head."""
    for head in HEADS:
        new = candidate.metrics.get(f"auc_{head}")
        old = candidate.metrics.get(f"baseline_auc_{head}")
        if new is not None and old is not None and new < old - tolerance:
            return False
    return any(k.startswith("auc_") for k in candidate.metrics)
