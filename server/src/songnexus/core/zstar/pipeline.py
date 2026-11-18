"""The Z-star pipeline: signals -> retrieval -> features -> ranking -> re-ranking.

``recommend`` is the one entry point the service calls. Randomness (walks,
exploration) comes from a seeded ``random.Random`` the caller derives from the
listener and the feed, so a feed can be reproduced exactly from its log.
"""

from __future__ import annotations

import enum
import random
from collections.abc import Mapping
from dataclasses import dataclass, field

from songnexus.core.zstar.catalog import Catalog
from songnexus.core.zstar.embed import Embeddings
from songnexus.core.zstar.features import SOURCE_FEATURES, featurize
from songnexus.core.zstar.ranker import PRIOR, Model
from songnexus.core.zstar.rerank import RerankConfig, Scored, rerank
from songnexus.core.zstar.retrieval import RetrievalConfig, Source, genre_affinity, retrieve
from songnexus.core.zstar.signals import Profile, Signals, build_profile


class ReasonKind(enum.StrEnum):
    """Why a card is in the feed (one per card, the strongest)."""

    CONNECTED = "CONNECTED"  # random walks: close to a seed through collaborators
    FANS_ALSO = "FANS_ALSO"  # co-listening with a seed
    SIMILAR = "SIMILAR"  # embedding neighbor of a seed
    GENRE = "GENRE"  # popular in a genre the listener likes
    FRIENDS = "FRIENDS"  # in friends' Top 5
    DISCOVER = "DISCOVER"  # exploration


REASON_FOR = {
    Source.WALK: ReasonKind.CONNECTED,
    Source.COLISTEN: ReasonKind.FANS_ALSO,
    Source.EMBED: ReasonKind.SIMILAR,
    Source.GENRE: ReasonKind.GENRE,
    Source.FRIENDS: ReasonKind.FRIENDS,
    Source.EXPLORE: ReasonKind.DISCOVER,
}
# How much a source's evidence counts when picking the reason to show.
REASON_STRENGTH = {
    Source.FRIENDS: 1.2,
    Source.COLISTEN: 1.1,
    Source.WALK: 1.0,
    Source.EMBED: 0.9,
    Source.GENRE: 0.6,
    Source.EXPLORE: 0.3,
}


@dataclass(frozen=True)
class Arm:
    """What an experiment arm changes."""

    retrieval: RetrievalConfig = field(default_factory=RetrievalConfig)
    rerank: RerankConfig = field(default_factory=RerankConfig)
    use_prior: bool = False


ARMS: dict[str, Arm] = {
    "control": Arm(),
    "diverse": Arm(rerank=RerankConfig(mmr_lambda=0.6, genre_max=1)),
    "explore": Arm(rerank=RerankConfig(explore_every=4)),
    "prior": Arm(use_prior=True),
}


@dataclass(frozen=True)
class Reason:
    """The reason shown on a card.

    Attributes:
        kind: Which reason.
        via: The seed artist (CONNECTED, FANS_ALSO, SIMILAR) or genre (GENRE).
        via_kind: Why the seed is a seed (FOLLOW, TOP, PLAYS, MORE_LIKE, ENGAGED).
        count: Friends who share the artist (FRIENDS).
    """

    kind: ReasonKind
    via: str | None = None
    via_kind: str | None = None
    count: int = 0


@dataclass(frozen=True)
class Item:
    """One feed card.

    Attributes:
        artist_id: The artist.
        value: Ranking value.
        heads: P(open), P(listen), P(negative).
        features: Exactly what the ranker saw (logged for training).
        sources: The sources that proposed the artist.
        reason: Why it is shown.
        exploratory: Placed in an exploration slot or never shown before.
    """

    artist_id: str
    value: float
    heads: Mapping[str, float]
    features: Mapping[str, float]
    sources: tuple[str, ...]
    reason: Reason
    exploratory: bool


@dataclass(frozen=True)
class Feed:
    """A ranked feed and how it was made."""

    items: tuple[Item, ...]
    profile: Profile
    model_version: str
    arm: str
    candidates: int


def _reason(
    sources: Mapping[Source, float],
    via: Mapping[Source, str],
    profile: Profile,
    friends: Mapping[str, int],
    artist_id: str,
) -> Reason:
    if not sources:
        return Reason(ReasonKind.DISCOVER)
    best = max(sources, key=lambda s: (sources[s] * REASON_STRENGTH[s], s.value))
    kind = REASON_FOR[best]
    seed = via.get(best)
    if kind is ReasonKind.FRIENDS:
        return Reason(kind, count=friends.get(artist_id, 0))
    if kind is ReasonKind.GENRE:
        return Reason(kind, via=seed)
    if kind is ReasonKind.DISCOVER or seed is None:
        return Reason(ReasonKind.DISCOVER)
    return Reason(kind, via=seed, via_kind=profile.seed_reasons.get(seed))


def recommend(
    catalog: Catalog,
    embeddings: Embeddings | None,
    signals: Signals,
    model: Model,
    *,
    rng: random.Random,
    arm: str = "control",
) -> Feed:
    """The listener's For You feed, best first."""
    settings = ARMS.get(arm, ARMS["control"])
    model = PRIOR if settings.use_prior else model
    profile = build_profile(signals)
    candidates = retrieve(
        catalog, embeddings, profile, signals.friends, rng=rng, config=settings.retrieval
    )
    affinity = genre_affinity(catalog, profile)
    features = featurize(
        catalog,
        embeddings,
        profile,
        affinity=affinity,
        engagement=signals.engagement,
        candidates=candidates,
    )

    scored: dict[str, tuple[float, dict[str, float]]] = {
        a: model.value(f) for a, f in features.items()
    }
    pool = [
        Scored(
            artist_id=a,
            value=value,
            exploratory=(Source.EXPLORE in candidates[a].scores or a not in signals.engagement),
            genre=catalog.primary_genre.get(a),
        )
        for a, (value, _) in scored.items()
    ]

    def similarity(a: str, b: str) -> float:
        return embeddings.similarity(a, b) if embeddings is not None else 0.0

    ordered = rerank(pool, similarity, rng, settings.rerank)
    items = []
    for s in ordered:
        candidate = candidates[s.artist_id]
        f = features[s.artist_id]
        evidence = {src: f[SOURCE_FEATURES[src]] for src in candidate.scores}
        items.append(
            Item(
                artist_id=s.artist_id,
                value=round(s.value, 6),
                heads={h: round(p, 6) for h, p in scored[s.artist_id][1].items()},
                features={k: round(v, 5) for k, v in f.items()},
                sources=tuple(sorted(src.value for src in candidate.scores)),
                reason=_reason(evidence, candidate.via, profile, signals.friends, s.artist_id),
                exploratory=s.exploratory,
            )
        )
    return Feed(
        items=tuple(items),
        profile=profile,
        model_version=model.version,
        arm=arm if arm in ARMS else "control",
        candidates=len(candidates),
    )
