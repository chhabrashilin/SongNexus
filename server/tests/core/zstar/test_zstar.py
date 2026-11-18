"""Z-star on a small synthetic catalog: two genre clusters joined by one bridge."""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

import pytest

from songnexus.core.zstar import evaluate, experiments, ranker
from songnexus.core.zstar.catalog import Catalog, _walk_neighbors
from songnexus.core.zstar.embed import Embeddings, build_embeddings
from songnexus.core.zstar.pipeline import ReasonKind, recommend
from songnexus.core.zstar.rerank import RerankConfig, Scored, rerank
from songnexus.core.zstar.signals import (
    NOT_INTERESTED_FOR,
    Engagement,
    Signals,
    build_profile,
    decay,
)

NOW = datetime(2026, 11, 18, tzinfo=UTC)
ROCK = [f"r{i}" for i in range(12)]
JAZZ = [f"j{i}" for i in range(12)]


def _cluster(ids: list[str]) -> dict[str, dict[str, float]]:
    adjacency: dict[str, dict[str, float]] = {a: {} for a in ids}
    for i, a in enumerate(ids):
        for b in ids[i + 1 : i + 4]:
            adjacency[a][b] = adjacency[b][a] = 3.0
    return adjacency


@pytest.fixture(scope="module")
def catalog() -> Catalog:
    adjacency = {**_cluster(ROCK), **_cluster(JAZZ)}
    adjacency["r11"]["j0"] = adjacency["j0"]["r11"] = 1.0  # the bridge
    colistening = {"r0": {"r5": 1, "r6": 2}, "r5": {"r0": 1}, "r6": {"r0": 2}}
    genres = {a: {"rock": 1.0} for a in ROCK} | {a: {"jazz": 1.0} for a in JAZZ}
    performers = frozenset(ROCK + JAZZ)
    popularity = {a: 1.0 - i / 24 for i, a in enumerate(ROCK + JAZZ)}
    return Catalog(
        version="test",
        names={a: a.upper() for a in performers},
        performers=performers,
        popularity=popularity,
        has_image=frozenset(ROCK[:6]),
        genres=genres,
        primary_genre={a: next(iter(g)) for a, g in genres.items()},
        genre_names={"rock": "Rock", "jazz": "Jazz"},
        genre_pool={
            "rock": tuple(sorted(ROCK, key=lambda a: -popularity[a])),
            "jazz": tuple(sorted(JAZZ, key=lambda a: -popularity[a])),
        },
        colistening=colistening,
        adjacency=adjacency,
        walk=_walk_neighbors(adjacency, colistening),
    )


@pytest.fixture(scope="module")
def embeddings(catalog: Catalog) -> Embeddings:
    genres = {a: list(g.items()) for a, g in catalog.genres.items()}
    return build_embeddings(catalog.adjacency, catalog.colistening, genres, "test", dimensions=16)


def test_embeddings_put_a_cluster_together(embeddings: Embeddings) -> None:
    same = embeddings.similarity("r1", "r2")
    other = embeddings.similarity("r1", "j5")
    assert same > other
    restored = Embeddings.from_payload(embeddings.to_payload())
    assert restored.ids == embeddings.ids
    assert abs(restored.similarity("r1", "r2") - same) < 1e-3


def test_decay_halves_after_one_half_life() -> None:
    assert decay(timedelta(days=30), timedelta(days=30)) == pytest.approx(0.5)
    assert decay(timedelta(0), timedelta(days=30)) == 1.0


def test_profile_seeds_exclusions_and_cold_start() -> None:
    signals = Signals(
        now=NOW,
        follows={"r0": NOW - timedelta(days=1)},
        plays={"r3": (50, NOW), "j1": (2, NOW)},
        not_interested={"r4": NOW - timedelta(days=2), "r9": NOW - NOT_INTERESTED_FOR * 2},
        blocked=frozenset({"j2"}),
    )
    profile = build_profile(signals)
    assert {"r0", "r3", "j1"} <= set(profile.seeds)
    assert profile.seed_reasons["r0"] == "FOLLOW"
    # Followed, blocked, recently not interested and well-known artists are out.
    assert {"r0", "j2", "r4", "r3"} <= profile.excluded
    assert "r9" not in profile.excluded  # the "not interested" expired
    assert "j1" not in profile.excluded  # two plays is not "known well"
    assert build_profile(Signals(now=NOW)).cold


def test_feed_follows_the_seeds_and_explains_itself(
    catalog: Catalog, embeddings: Embeddings
) -> None:
    signals = Signals(now=NOW, follows={"r0": NOW, "r1": NOW})
    feed = recommend(catalog, embeddings, signals, ranker.PRIOR, rng=random.Random(1))
    ids = [i.artist_id for i in feed.items]
    assert ids, "the feed is empty"
    assert "r0" not in ids
    assert "r1" not in ids
    top = ids[:5]
    assert sum(1 for a in top if a.startswith("r")) >= 3  # rock leads for a rock fan
    first = feed.items[0]
    assert first.reason.kind is not ReasonKind.DISCOVER
    assert set(first.heads) == {"open", "listen", "negative"}
    assert feed.model_version == ranker.PRIOR_VERSION
    # Same inputs, same seed: the same feed.
    again = recommend(catalog, embeddings, signals, ranker.PRIOR, rng=random.Random(1))
    assert [i.artist_id for i in again.items] == ids


def test_not_interested_and_blocks_never_appear(catalog: Catalog, embeddings: Embeddings) -> None:
    signals = Signals(
        now=NOW,
        follows={"r0": NOW},
        not_interested={"r2": NOW},
        blocked=frozenset({"r3"}),
    )
    ids = [
        i.artist_id
        for i in recommend(catalog, embeddings, signals, ranker.PRIOR, rng=random.Random(2)).items
    ]
    assert "r2" not in ids
    assert "r3" not in ids


def test_cold_start_still_fills_a_feed(catalog: Catalog) -> None:
    feed = recommend(catalog, None, Signals(now=NOW), ranker.PRIOR, rng=random.Random(3))
    assert feed.profile.cold
    assert len(feed.items) >= 10
    assert all(i.reason.kind is ReasonKind.DISCOVER for i in feed.items)


def test_fatigue_lowers_what_was_ignored(catalog: Catalog, embeddings: Embeddings) -> None:
    base = Signals(now=NOW, follows={"r0": NOW})
    fresh = recommend(catalog, embeddings, base, ranker.PRIOR, rng=random.Random(4))
    target = fresh.items[0].artist_id
    tired = Signals(
        now=NOW,
        follows={"r0": NOW},
        engagement={target: Engagement(impressions=5, recent_impressions=5, skips=4, last_at=NOW)},
    )
    after = recommend(catalog, embeddings, tired, ranker.PRIOR, rng=random.Random(4))
    before_value = fresh.items[0].value
    after_value = next(i.value for i in after.items if i.artist_id == target)
    assert after_value < before_value


def test_rerank_spaces_genres() -> None:
    items = [Scored(f"a{i}", 1.0 - i / 100, False, "rock") for i in range(6)] + [
        Scored(f"b{i}", 0.5 - i / 100, False, "jazz") for i in range(6)
    ]
    order = rerank(
        items,
        lambda a, b: 0.0,
        random.Random(0),
        RerankConfig(genre_window=3, genre_max=2, explore_every=0),
    )
    genres = [s.genre for s in order]
    for i in range(len(genres) - 2):
        window = genres[i : i + 3]
        assert window.count("rock") <= 2 or "jazz" not in genres[i:]


def test_experiments_are_stable_and_split_traffic() -> None:
    spec = experiments.parse("zstar-test:diverse=0.5")
    assert spec is not None
    arms = [experiments.assign(f"user{i}", spec) for i in range(2000)]
    assert experiments.assign("user7", spec) == arms[7]
    share = arms.count("diverse") / len(arms)
    assert 0.45 < share < 0.55
    assert experiments.assign("anyone", None) == "control"
    with pytest.raises(ValueError, match="Bad experiment"):
        experiments.parse("x:a=0.7,b=0.6")


def test_training_learns_a_planted_signal() -> None:
    rng = random.Random(5)
    examples = []
    for _ in range(3000):
        f = {"bias": 1.0, "colisten": rng.random(), "explore": rng.random()}
        opened = rng.random() < 0.05 + 0.6 * f["colisten"]
        examples.append(ranker.Example(f, {"open": opened, "listen": False, "negative": False}))
    model = ranker.train(examples, "trained-test")
    assert model is not None
    assert model.weights["open"]["colisten"] > 1.0
    # Opens happen with probability 0.05 + 0.6 * colisten, so ~0.72 is the best any
    # model can do; the trained head should get close and beat the prior.
    assert model.metrics["auc_open"] > 0.69
    assert model.metrics["auc_open"] >= model.metrics["baseline_auc_open"] - 0.005
    assert ranker.better(model)
    restored = ranker.Model.from_payload(model.to_payload())
    assert restored.weights == model.weights
    assert ranker.train(examples[:10], "too-small") is None


def test_offline_metrics(catalog: Catalog, embeddings: Embeddings) -> None:
    users = evaluate.split_users([dict.fromkeys(ROCK, 5)], hidden_share=0.25, min_artists=5)
    assert len(users) == 1
    assert len(users[0].hidden) == 3
    report = evaluate.run(
        "popularity",
        evaluate.popularity_baseline(catalog),
        users,
        catalog=catalog,
        embeddings=embeddings,
        k=5,
    )
    assert 0.0 <= report.recall <= 1.0
    assert report.coverage > 0
    assert evaluate.ndcg(["x", "y"], frozenset({"x"}), 2) == 1.0
