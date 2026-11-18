"""Ranking features: what the ranker knows about one listener and one candidate.

Every feature is a float, mostly in [0, 1], named in ``FEATURES`` (the model's
column order). Features are logged with every served item (feature logging),
so the ranker trains on exactly what it saw at serving time.
"""

from __future__ import annotations

import math
from collections.abc import Mapping

import numpy as np

from songnexus.core.zstar.catalog import Catalog
from songnexus.core.zstar.embed import Embeddings
from songnexus.core.zstar.retrieval import Candidate, Source
from songnexus.core.zstar.signals import Engagement, Profile

FEATURES: tuple[str, ...] = (
    "bias",
    "walk",
    "colisten",
    "embed",
    "genre",
    "friends",
    "explore",
    "sources",
    "genre_affinity",
    "genre_penalty",
    "negative_similarity",
    "seed_similarity",
    "popularity",
    "novelty",
    "has_image",
    "seen_before",
    "opened_before",
    "skip_rate",
    "fatigue",
)
SOURCE_FEATURES = {
    Source.WALK: "walk",
    Source.COLISTEN: "colisten",
    Source.EMBED: "embed",
    Source.GENRE: "genre",
    Source.FRIENDS: "friends",
    Source.EXPLORE: "explore",
}
FATIGUE_IMPRESSIONS = 3


def _normalizers(candidates: Mapping[str, Candidate]) -> dict[Source, float]:
    peaks: dict[Source, float] = {}
    for candidate in candidates.values():
        for source, score in candidate.scores.items():
            value = math.log1p(score) if source is Source.WALK else score
            peaks[source] = max(peaks.get(source, 0.0), value)
    return peaks


def featurize(
    catalog: Catalog,
    embeddings: Embeddings | None,
    profile: Profile,
    *,
    affinity: Mapping[str, float],
    engagement: Mapping[str, Engagement],
    candidates: Mapping[str, Candidate],
) -> dict[str, dict[str, float]]:
    """Artist -> feature name -> value, for every candidate."""
    peaks = _normalizers(candidates)
    negatives = None
    seeds_matrix = None
    if embeddings is not None:
        neg_rows = [r for a in profile.negative_artists if (r := embeddings.row(a)) is not None]
        negatives = embeddings.matrix[neg_rows] if neg_rows else None
        seed_rows = [r for a in profile.seeds if (r := embeddings.row(a)) is not None]
        seeds_matrix = embeddings.matrix[seed_rows] if seed_rows else None

    out: dict[str, dict[str, float]] = {}
    for artist_id, candidate in candidates.items():
        f = dict.fromkeys(FEATURES, 0.0)
        f["bias"] = 1.0
        for source, score in candidate.scores.items():
            value = math.log1p(score) if source is Source.WALK else score
            peak = peaks.get(source) or 1.0
            f[SOURCE_FEATURES[source]] = max(value, 0.0) / peak
        f["sources"] = len(candidate.scores) / len(SOURCE_FEATURES)
        genres = catalog.genres.get(artist_id, {})
        f["genre_affinity"] = sum(affinity.get(g, 0.0) * s for g, s in genres.items())
        f["genre_penalty"] = sum(profile.genre_penalty.get(g, 0.0) * s for g, s in genres.items())
        vector = embeddings.vector(artist_id) if embeddings is not None else None
        if vector is not None and negatives is not None:
            f["negative_similarity"] = max(float((negatives @ vector).max()), 0.0)
        if vector is not None and seeds_matrix is not None:
            f["seed_similarity"] = max(float(np.max(seeds_matrix @ vector)), 0.0)
        popularity = catalog.popularity.get(artist_id, 0.0)
        f["popularity"] = popularity
        f["novelty"] = 1.0 - popularity
        f["has_image"] = 1.0 if artist_id in catalog.has_image else 0.0
        e = engagement.get(artist_id)
        if e is not None:
            f["seen_before"] = min(math.log1p(e.impressions) / math.log1p(10), 1.0)
            f["opened_before"] = 1.0 if (e.opens or e.listens) else 0.0
            f["skip_rate"] = e.skips / e.impressions if e.impressions else 0.0
            f["fatigue"] = (
                1.0
                if (e.recent_impressions >= FATIGUE_IMPRESSIONS and not (e.opens or e.listens))
                else 0.0
            )
        out[artist_id] = f
    return out


def vector(features: Mapping[str, float]) -> list[float]:
    """Features in model column order (unknown names ignored, missing ones 0)."""
    return [float(features.get(name, 0.0)) for name in FEATURES]
