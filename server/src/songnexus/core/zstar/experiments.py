"""Experiments: stable, independent assignment of listeners to arms.

A listener's arm is a pure function of their ID and the experiment name
(SHA-256 into 10,000 buckets), so it never changes between requests, needs no
storage, and different experiments are independent of each other. The arm is
logged with every feed, so outcomes can be compared per arm offline.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass

BUCKETS = 10_000


@dataclass(frozen=True)
class Experiment:
    """An experiment: name and arms with their share of traffic (shares sum to <= 1).

    Listeners outside every arm's share get ``control``.
    """

    name: str
    arms: Mapping[str, float]


def bucket(user_id: str, experiment: str) -> int:
    """The listener's bucket in [0, BUCKETS) for an experiment."""
    digest = hashlib.sha256(f"{experiment}:{user_id}".encode()).digest()
    return int.from_bytes(digest[:8], "big") % BUCKETS


def assign(user_id: str, experiment: Experiment | None) -> str:
    """The arm a listener is in (``control`` without an experiment)."""
    if experiment is None:
        return "control"
    point = bucket(user_id, experiment.name)
    edge = 0.0
    for arm, share in sorted(experiment.arms.items()):
        edge += share * BUCKETS
        if point < edge:
            return arm
    return "control"


def parse(spec: str | None) -> Experiment | None:
    """Reads ``name:arm=share,arm=share`` (e.g. ``zstar-mmr:diverse=0.1``); None when empty.

    Raises:
        ValueError: On a malformed spec or shares above 1.
    """
    if not spec or not spec.strip():
        return None
    name, _, arms_text = spec.partition(":")
    arms: dict[str, float] = {}
    for part in filter(None, (p.strip() for p in arms_text.split(","))):
        arm, _, share = part.partition("=")
        arms[arm.strip()] = float(share)
    if not name.strip() or not arms or sum(arms.values()) > 1.0 + 1e-9:
        raise ValueError(f"Bad experiment spec: {spec!r}")
    return Experiment(name=name.strip(), arms=arms)
