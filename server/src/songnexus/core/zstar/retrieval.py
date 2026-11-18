"""Candidate retrieval: several independent sources, merged with provenance.

Each source proposes artists with a raw score and the seed (or genre) that led
there, so every recommendation can say why. Sources:

- ``WALK``: random walks with restart from the seeds over credits and
  co-listening (Pixie, Eksombatchai et al., WWW 2018). Steps are split between
  seeds by weight; visit counts are combined with Pixie's multi-hit boost
  (sum of square roots, squared), which favors artists several seeds reach.
- ``COLISTEN``: artists played in the same sessions as a seed (aggregate data).
- ``EMBED``: nearest neighbors of the listener's taste vector (the weighted
  mean of seed embeddings, pushed away from "not interested" artists).
- ``GENRE``: popular artists in the listener's strongest top-level genres
  (from seeds and settings, lowered by "less of this genre").
- ``FRIENDS``: artists the listener's friends share in their Top 5.
- ``EXPLORE``: a popularity-weighted random sample, so the feed keeps learning
  what else the listener likes (and so a new listener sees something good).
"""

from __future__ import annotations

import enum
import math
import random
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field

import numpy as np

from songnexus.core.zstar.catalog import Catalog
from songnexus.core.zstar.embed import Embeddings
from songnexus.core.zstar.signals import Profile


class Source(enum.StrEnum):
    """Where a candidate came from."""

    WALK = "WALK"
    COLISTEN = "COLISTEN"
    EMBED = "EMBED"
    GENRE = "GENRE"
    FRIENDS = "FRIENDS"
    EXPLORE = "EXPLORE"


@dataclass(frozen=True)
class RetrievalConfig:
    """Per-source budgets (an experiment arm can change them)."""

    walk_steps: int = 30_000
    walk_restart: float = 0.35
    walk_top: int = 200
    colisten_per_seed: int = 40
    colisten_top: int = 200
    embed_top: int = 250
    negative_push: float = 0.35
    genre_count: int = 4
    genre_top: int = 60
    friends_top: int = 50
    explore_count: int = 60
    explore_pool: int = 1500
    cold_explore_count: int = 200


@dataclass
class Candidate:
    """A proposed artist: raw score and provenance per source."""

    artist_id: str
    scores: dict[Source, float] = field(default_factory=dict)
    via: dict[Source, str] = field(default_factory=dict)

    def add(self, source: Source, score: float, via: str | None) -> None:
        """Records a source's score (keeping the best) and what led there."""
        if score > self.scores.get(source, float("-inf")):
            self.scores[source] = score
            if via is not None:
                self.via[source] = via


def _top(scores: Mapping[str, float], k: int) -> list[tuple[str, float]]:
    return sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))[:k]


def random_walks(
    catalog: Catalog,
    seeds: Mapping[str, float],
    rng: random.Random,
    config: RetrievalConfig,
) -> dict[str, tuple[float, str]]:
    """Pixie walks: artist -> (boosted visit score, the seed that visited most)."""
    total = sum(seeds.values())
    if not total:
        return {}
    visits: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for seed, weight in sorted(seeds.items()):
        if seed not in catalog.walk:
            continue
        steps = max(int(config.walk_steps * weight / total), 50)
        current = seed
        for _ in range(steps):
            if rng.random() < config.walk_restart:
                current = seed
            nbrs = catalog.walk.get(current)
            if nbrs is None:
                current = seed
                continue
            current = nbrs.pick(rng.random())
            if current != seed:
                visits[current][seed] += 1
    out = {}
    for artist_id, by_seed in visits.items():
        boosted = sum(math.sqrt(c) for c in by_seed.values()) ** 2
        via = max(by_seed.items(), key=lambda kv: (kv[1], kv[0]))[0]
        out[artist_id] = (boosted, via)
    return out


def colistening(
    catalog: Catalog, seeds: Mapping[str, float], config: RetrievalConfig
) -> dict[str, tuple[float, str]]:
    """Co-listened artists: sum over seeds of weight / sqrt(rank)."""
    scores: dict[str, float] = defaultdict(float)
    best: dict[str, tuple[float, str]] = {}
    for seed, weight in seeds.items():
        ranked = sorted(catalog.colistening.get(seed, {}).items(), key=lambda kv: kv[1])
        for other, rank in ranked[: config.colisten_per_seed]:
            contribution = weight / math.sqrt(rank)
            scores[other] += contribution
            if contribution > best.get(other, (0.0, ""))[0]:
                best[other] = (contribution, seed)
    return {a: (s, best[a][1]) for a, s in _top(scores, config.colisten_top)}


def nearest(
    embeddings: Embeddings,
    profile: Profile,
    config: RetrievalConfig,
    allowed: frozenset[str],
) -> dict[str, tuple[float, str]]:
    """Cosine neighbors of the taste vector, each with its most similar seed."""
    taste = embeddings.mean(profile.seeds)
    if taste is None:
        return {}
    negative = embeddings.mean(profile.negative_artists)
    if negative is not None:
        taste = taste - config.negative_push * negative
        norm = float(np.linalg.norm(taste))
        if norm == 0:
            return {}
        taste = taste / norm
    sims = embeddings.matrix @ taste
    order = np.argsort(-sims)
    picked: list[tuple[int, float]] = []
    for i in order:
        artist_id = embeddings.ids[int(i)]
        if artist_id in allowed and artist_id not in profile.seeds:
            picked.append((int(i), float(sims[int(i)])))
            if len(picked) >= config.embed_top:
                break
    seed_rows = [(s, r) for s in profile.seeds if (r := embeddings.row(s)) is not None]
    if not picked or not seed_rows:
        return {}
    seed_matrix = embeddings.matrix[[r for _, r in seed_rows]]
    cand_matrix = embeddings.matrix[[i for i, _ in picked]]
    closest = (cand_matrix @ seed_matrix.T).argmax(axis=1)
    return {
        embeddings.ids[i]: (sim, seed_rows[int(c)][0])
        for (i, sim), c in zip(picked, closest, strict=True)
    }


def genre_affinity(catalog: Catalog, profile: Profile) -> dict[str, float]:
    """Top-level genre -> affinity in [0, 1] (seed genre mix, settings, penalties)."""
    scores: dict[str, float] = defaultdict(float)
    for seed, weight in profile.seeds.items():
        for genre, share in catalog.genres.get(seed, {}).items():
            scores[genre] += weight * share
    total = sum(scores.values()) or 1.0
    affinity = {g: s / total for g, s in scores.items()}
    for genre in profile.preferred_genres:
        affinity[genre] = affinity.get(genre, 0.0) + 0.3
    for genre, penalty in profile.genre_penalty.items():
        if genre in affinity:
            affinity[genre] *= 1.0 - 0.8 * penalty
    peak = max(affinity.values(), default=0.0)
    return {g: a / peak for g, a in affinity.items() if a > 0} if peak else {}


def by_genre(
    catalog: Catalog, affinity: Mapping[str, float], config: RetrievalConfig
) -> dict[str, tuple[float, str]]:
    """Popular artists of the strongest genres, scored by affinity and popularity."""
    out: dict[str, tuple[float, str]] = {}
    for genre, weight in _top(affinity, config.genre_count):
        for artist_id in catalog.genre_pool.get(genre, ())[: config.genre_top]:
            share = catalog.genres.get(artist_id, {}).get(genre, 0.0)
            score = weight * share * (0.5 + 0.5 * catalog.popularity.get(artist_id, 0.0))
            if score > out.get(artist_id, (0.0, ""))[0]:
                out[artist_id] = (score, genre)
    return out


def explore(
    catalog: Catalog, rng: random.Random, count: int, pool: int
) -> dict[str, tuple[float, str]]:
    """A popularity-weighted sample of the most popular performers (no replacement)."""
    candidates = list(catalog.popular[:pool])
    weights = [0.1 + catalog.popularity.get(a, 0.0) for a in candidates]
    chosen: dict[str, tuple[float, str]] = {}
    while candidates and len(chosen) < count:
        i = rng.choices(range(len(candidates)), weights=weights, k=1)[0]
        artist_id = candidates.pop(i)
        weights.pop(i)
        chosen[artist_id] = (catalog.popularity.get(artist_id, 0.0), "")
    return chosen


def retrieve(
    catalog: Catalog,
    embeddings: Embeddings | None,
    profile: Profile,
    friends: Mapping[str, int],
    *,
    rng: random.Random,
    config: RetrievalConfig | None = None,
) -> dict[str, Candidate]:
    """Merges every source's proposals, dropping seeds, exclusions and non-performers."""
    config = config or RetrievalConfig()
    allowed = catalog.performers - profile.excluded
    candidates: dict[str, Candidate] = {}

    def take(source: Source, proposals: Mapping[str, tuple[float, str]]) -> None:
        for artist_id, (score, via) in proposals.items():
            if artist_id not in allowed or artist_id in profile.seeds:
                continue
            candidate = candidates.setdefault(artist_id, Candidate(artist_id))
            candidate.add(source, score, via or None)

    seeds = profile.seeds
    if seeds:
        walks = random_walks(catalog, seeds, rng, config)
        best = _top({a: score for a, (score, _) in walks.items()}, config.walk_top)
        take(Source.WALK, {a: walks[a] for a, _ in best})
        take(Source.COLISTEN, colistening(catalog, seeds, config))
        if embeddings is not None:
            take(Source.EMBED, nearest(embeddings, profile, config, allowed))
    take(Source.GENRE, by_genre(catalog, genre_affinity(catalog, profile), config))
    shared = _top({a: float(n) for a, n in friends.items()}, config.friends_top)
    take(Source.FRIENDS, {a: (n, "") for a, n in shared})
    count = config.cold_explore_count if profile.cold else config.explore_count
    take(Source.EXPLORE, explore(catalog, rng, count, config.explore_pool))
    return candidates
