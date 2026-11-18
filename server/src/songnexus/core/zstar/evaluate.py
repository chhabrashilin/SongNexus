"""Offline evaluation: does Z-star find what listeners actually play?

Protocol (leave-some-out on an independent population, e.g. Last.fm 360K):
for each listener, a random share of their catalog artists is hidden; the rest
(with play counts) become their signals; the recommender ranks artists; the
hidden ones are the relevant set. Reported, averaged over listeners:

- ``recall@k``: share of hidden artists in the top k;
- ``ndcg@k``: discounted cumulative gain of hits, normalized by the ideal;
- ``coverage``: share of the catalog's performers recommended to anyone;
- ``diversity``: 1 − mean pairwise cosine similarity within a top k list;
- ``novelty``: mean (1 − popularity) of recommended artists.

Accuracy alone rewards recommending the most popular artists to everyone, so
the popularity baseline is always reported next to Z-star, and coverage,
diversity and novelty sit next to accuracy.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass

from songnexus.core.zstar.catalog import Catalog
from songnexus.core.zstar.embed import Embeddings

Recommender = Callable[[Mapping[str, int], int], Sequence[str]]


@dataclass(frozen=True)
class EvalUser:
    """One held-out listener: visible artists with plays, hidden artists."""

    visible: Mapping[str, int]
    hidden: frozenset[str]


@dataclass(frozen=True)
class Report:
    """Averaged metrics for one recommender."""

    name: str
    users: int
    recall: float
    ndcg: float
    coverage: float
    diversity: float
    novelty: float
    k: int

    def as_dict(self) -> dict[str, float | int | str]:
        """JSON-safe form."""
        return {
            "name": self.name,
            "users": self.users,
            f"recall@{self.k}": round(self.recall, 4),
            f"ndcg@{self.k}": round(self.ndcg, 4),
            "coverage": round(self.coverage, 4),
            "diversity": round(self.diversity, 4),
            "novelty": round(self.novelty, 4),
        }


def split_users(
    listeners: Iterable[Mapping[str, int]],
    *,
    hidden_share: float = 0.2,
    min_artists: int = 10,
    seed: int = 13,
) -> list[EvalUser]:
    """Hides ``hidden_share`` of each listener's artists (at least one), at random."""
    rng = random.Random(seed)  # noqa: S311 - a reproducible split, not a secret
    out = []
    for artists in listeners:
        if len(artists) < min_artists:
            continue
        ids = sorted(artists)
        rng.shuffle(ids)
        cut = max(1, int(len(ids) * hidden_share))
        hidden = frozenset(ids[:cut])
        out.append(EvalUser({a: artists[a] for a in ids[cut:]}, hidden))
    return out


def ndcg(ranked: Sequence[str], relevant: frozenset[str], k: int) -> float:
    """NDCG@k with binary relevance."""
    gain = sum(1.0 / math.log2(i + 2) for i, a in enumerate(ranked[:k]) if a in relevant)
    ideal = sum(1.0 / math.log2(i + 2) for i in range(min(len(relevant), k)))
    return gain / ideal if ideal else 0.0


def diversity(ranked: Sequence[str], embeddings: Embeddings | None) -> float:
    """1 − mean pairwise cosine similarity of the list (0 without embeddings)."""
    if embeddings is None:
        return 0.0
    ids = [a for a in ranked if embeddings.row(a) is not None]
    pairs = [(a, b) for i, a in enumerate(ids) for b in ids[i + 1 :]]
    if not pairs:
        return 0.0
    return 1.0 - sum(embeddings.similarity(a, b) for a, b in pairs) / len(pairs)


def run(
    name: str,
    recommender: Recommender,
    users: Sequence[EvalUser],
    *,
    catalog: Catalog,
    embeddings: Embeddings | None,
    k: int = 20,
) -> Report:
    """Evaluates one recommender over the held-out listeners."""
    recalls, ndcgs, divs, novs = [], [], [], []
    shown: set[str] = set()
    for user in users:
        ranked = list(recommender(user.visible, k))[:k]
        shown.update(ranked)
        recalls.append(len(set(ranked) & user.hidden) / len(user.hidden))
        ndcgs.append(ndcg(ranked, user.hidden, k))
        divs.append(diversity(ranked, embeddings))
        novs.append(
            sum(1.0 - catalog.popularity.get(a, 0.0) for a in ranked) / len(ranked)
            if ranked
            else 0.0
        )
    n = len(users) or 1
    return Report(
        name=name,
        users=len(users),
        recall=sum(recalls) / n,
        ndcg=sum(ndcgs) / n,
        coverage=len(shown) / (len(catalog.performers) or 1),
        diversity=sum(divs) / n,
        novelty=sum(novs) / n,
        k=k,
    )


def popularity_baseline(catalog: Catalog) -> Recommender:
    """Recommends the most popular performers the listener has not played."""
    popular = catalog.popular

    def recommend(visible: Mapping[str, int], k: int) -> Sequence[str]:
        return [a for a in popular if a not in visible][:k]

    return recommend
