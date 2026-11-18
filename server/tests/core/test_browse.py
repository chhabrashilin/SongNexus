"""Browse index, shelves, recommendations, taste profiles and path tracks on hand-built graphs."""

from __future__ import annotations

import itertools
import random
from collections import deque
from datetime import date

import pytest

from songnexus.core import recommend as rec
from songnexus.core import shelves, taste
from songnexus.core.browse import (
    BrowseFacts,
    BrowseIndex,
    LabelFact,
    RecordingFact,
    build_index,
    step_track,
)
from songnexus.core.graph.model import (
    ArtistGraph,
    ArtistNode,
    EdgeKind,
    GenreShare,
    SubjectType,
)
from songnexus.core.listening import MIN_LISTENERS

KINDS = frozenset(EdgeKind) - {EdgeKind.LABEL_MATES, EdgeKind.ENGINEERED}
GENRES = {"g-pop": "pop", "g-rock": "rock", "g-jazz": "jazz", "g-indie": "indie rock"}


def _node(artist_id: str, *genres: tuple[str, float]) -> ArtistNode:
    return ArtistNode(
        artist_id,
        artist_id.upper(),
        "full",
        genres=tuple(GenreShare(g, GENRES[g], s) for g, s in genres),
    )


def _graph() -> ArtistGraph:
    """Artists a..h. ``prod`` produced for a, b, c; a and d perform together."""
    graph = ArtistGraph("v1")
    for node in (
        _node("a", ("g-pop", 1.0)),
        _node("b", ("g-indie", 0.7), ("g-pop", 0.3)),
        _node("c", ("g-jazz", 1.0)),
        _node("d", ("g-rock", 1.0)),
        _node("e", ("g-jazz", 1.0)),
        _node("prod"),
        _node("far"),
        _node("x"),
    ):
        graph.add_node(node)
    graph.genre_names.update(GENRES)
    graph.genre_parents["g-indie"] = frozenset({"g-rock"})

    def produced(producer: str, performer: str, recording: str) -> None:
        graph.add_evidence(
            producer,
            performer,
            EdgeKind.PRODUCED_FOR,
            SubjectType.RECORDING,
            recording,
            u_role="producer",
            v_role="primary",
        )

    produced("prod", "a", "r-a1")
    produced("prod", "a", "r-a2")
    produced("prod", "b", "r-b1")
    produced("prod", "c", "r-c1")
    graph.add_evidence(
        "a", "d", EdgeKind.PERFORMED_WITH, SubjectType.RECORDING, "r-ad", u_role="primary",
        v_role="primary",
    )  # fmt: skip
    graph.add_evidence(
        "d", "e", EdgeKind.PERFORMED_WITH, SubjectType.RELEASE, "rel-de", u_role="primary",
        v_role="primary",
    )  # fmt: skip
    graph.add_evidence(
        "e", "far", EdgeKind.MEMBER_OF, SubjectType.RELATION, "rel-1", u_role="member",
        v_role="group",
    )  # fmt: skip
    for rid, title in [("r-a1", "A One"), ("r-a2", "A Two"), ("r-ad", "Duet")]:
        graph.subject_titles[rid] = title
    return graph


def _facts() -> BrowseFacts:
    def recording(rid: str, day: str | None, *credits: tuple[str, str]) -> RecordingFact:
        return RecordingFact(rid, rid.upper(), day, credits)

    return BrowseFacts(
        recordings=[
            recording("r-a1", "1999-11-16", ("a", "primary"), ("prod", "producer")),
            recording("r-a2", "2004-11-16", ("a", "primary"), ("prod", "producer")),
            recording("r-b1", "2010-03-01", ("b", "primary"), ("prod", "producer")),
            recording("r-c1", "2012", ("c", "primary"), ("prod", "producer")),
            recording("r-c2", "2013-05-05", ("prod", "producer"), ("x", "primary")),
            recording("r-c3", "2014-05-05", ("prod", "producer"), ("x", "primary")),
            recording("r-ad", "2001-11-16", ("a", "primary"), ("d", "primary")),
            recording("r-de", "1985-02-02", ("d", "primary")),
        ],
        release_tracks={"rel-de": ("r-de",)},
        release_artists={"rel-de": ("d", "e")},
        labels=[
            LabelFact("lbl-small", "Small", frozenset({"rel-1"}), frozenset({"c", "e"})),
            LabelFact("lbl-big", "Big", frozenset({"rel-2", "rel-3"}), frozenset({"a", "c", "x"})),
        ],
        colistening={"a": [("e", 4)], "e": [("a", 9)]},
        listeners={"a": 5000, "e": MIN_LISTENERS, "c": 10},
    )


@pytest.fixture
def index() -> BrowseIndex:
    return build_index(_graph(), _facts())


def test_index_counts_credits_genres_and_days(index: BrowseIndex) -> None:
    assert index.degree["prod"] == 3
    assert index.recordings_by_role["prod"]["producer"] == {
        "r-a1", "r-a2", "r-b1", "r-c1", "r-c2", "r-c3",
    }  # fmt: skip
    assert index.primary_artists["r-ad"] == ("a", "d")
    assert sorted(index.by_month_day["11-16"]) == ["r-a1", "r-a2", "r-ad"]
    assert index.genre_roots["g-indie"] == {"g-rock"}
    assert index.primary_root["b"] == "g-rock"  # indie (0.7) counts toward rock
    assert "prod" not in index.primary_root
    assert index.performers >= {"a", "b", "c", "d", "e", "x"}
    assert "prod" not in index.performers
    assert index.genre_artists("g-rock") == ["d", "b"]  # d has more collaborators
    assert index.genre_artists("g-rock", include_subgenres=False) == ["d"]


def test_shelves_carry_counts_that_match_the_facts(index: BrowseIndex) -> None:
    hits = shelves.behind_the_hits(index)
    assert [i.artist_id for i in hits.items] == ["prod"]
    assert dict(hits.items[0].reason.params) == {"count": 6, "led": 0, "performers": 4}
    connectors = shelves.super_connectors(index)
    assert connectors.items[0].artist_id == "prod"
    assert dict(connectors.items[0].reason.params) == {"count": 3}
    degrees = [dict(i.reason.params)["count"] for i in connectors.items]
    assert degrees == sorted(degrees, reverse=True)
    bridges = shelves.genre_bridges(index)
    assert [i.artist_id for i in bridges.items] == ["prod"]  # pop, rock, jazz
    assert dict(bridges.items[0].reason.params)["count"] == 3


def test_on_this_day_looks_back_one_per_lead_artist(index: BrowseIndex) -> None:
    shelf = shelves.on_this_day(index, date(2026, 11, 16))
    assert shelf.kind is shelves.ShelfKind.ON_THIS_DAY
    assert dict(shelf.params) == {"month": 11, "day": 16}
    # All three 11-16 recordings are led by a (the duet's best-connected lead): one per lead,
    # the earliest wins.
    assert [i.recording_id for i in shelf.items] == ["r-a1"]
    assert dict(shelf.items[0].reason.params) == {"year": 1999, "yearsAgo": 27}
    assert [i.recording_id for i in shelves.on_this_day(index, date(2000, 11, 16)).items] == [
        "r-a1"
    ]  # later releases are not "on this day" yet
    assert not shelves.on_this_day(index, date(2026, 1, 1)).items


def test_decade_and_label_shelves(index: BrowseIndex) -> None:
    decades = {s.id: s for s in shelves.decade_shelves(index)}
    assert list(decades) == ["decade-2010", "decade-2000", "decade-1990", "decade-1980"]
    top = decades["decade-2010"].items[0]
    assert top.artist_id == "prod"
    assert dict(top.reason.params) == {"count": 4, "decade": 2010, "role": "producer"}
    label_shelf = shelves.labels(index)
    assert [i.label_id for i in label_shelf.items] == ["lbl-big", "lbl-small"]
    assert dict(label_shelf.items[0].reason.params) == {"count": 2, "artists": 3}


def test_catalog_shelves_are_deterministic(index: BrowseIndex) -> None:
    first = shelves.catalog_shelves(index)
    assert first == shelves.catalog_shelves(build_index(_graph(), _facts()))
    genre_ids = [s.genre_id for s in first if s.kind is shelves.ShelfKind.GENRE]
    # Two artists each (rock through indie); ties by name. Indie is not top level.
    assert genre_ids == ["g-jazz", "g-pop", "g-rock"]
    shown = [i.artist_id for s in first if s.kind is shelves.ShelfKind.GENRE for i in s.items]
    assert len(shown) == len(set(shown))  # genre shelves never repeat an artist
    day = shelves.on_this_day(index, date(2026, 11, 16))
    assert shelves.home_shelves(first, day)[3] == day


def test_recommendations_are_unconnected_and_explained(index: BrowseIndex) -> None:
    results = rec.recommend(index, "a")
    by_artist = {r.artist_id: r for r in results}
    assert "d" not in by_artist  # direct connections
    assert "prod" not in by_artist
    assert "a" not in by_artist
    assert by_artist["b"].via == ("prod",)
    assert by_artist["b"].shared_count == 1
    assert by_artist["e"].listening_rank == 4  # better of 4 (a's list) and 9 (e's list)
    assert by_artist["e"].listening_strength is not None
    assert rec.ReasonKind.SAME_LABEL in by_artist["x"].reasons
    for item in results:
        assert item.reasons
    scores = [r.score for r in results]
    assert scores == sorted(scores, reverse=True)


def test_recommendations_respect_blocks_and_the_listener_floor(index: BrowseIndex) -> None:
    blocked = rec.recommend(index, "a", allowed=lambda x: x != "prod")
    assert all("prod" not in r.via for r in blocked)
    assert "b" not in {r.artist_id for r in blocked}  # its only reason went through prod
    # c has 10 listeners: below the floor, so no listening reason is ever given for it.
    assert all(r.listening_rank is None for r in rec.recommend(index, "c"))


def _random_index(seed: int) -> BrowseIndex:
    rng = random.Random(seed)
    graph = ArtistGraph("r")
    names = [f"n{i:02d}" for i in range(30)]
    for n in names:
        graph.add_node(ArtistNode(n, n, "full"))
    for u, v in itertools.combinations(names, 2):
        if rng.random() < 0.08:
            graph.add_evidence(
                u, v, EdgeKind.PERFORMED_WITH, SubjectType.RECORDING, f"r-{u}-{v}",
                u_role="primary", v_role="primary",
            )  # fmt: skip
    facts = BrowseFacts(
        recordings=[RecordingFact(f"p-{n}", n, "2000", ((n, "primary"),)) for n in names]
    )
    return build_index(graph, facts)


def _distances(index: BrowseIndex, source: str) -> dict[str, int]:
    seen = {source: 0}
    queue = deque([source])
    while queue:
        node = queue.popleft()
        for other in index.adjacency[node]:
            if other not in seen:
                seen[other] = seen[node] + 1
                queue.append(other)
    return seen


@pytest.mark.parametrize("seed", range(25))
def test_recommendations_match_brute_force_on_random_graphs(seed: int) -> None:
    index = _random_index(seed)
    adjacency = index.adjacency
    for artist in list(adjacency)[:5]:
        results = rec.recommend(index, artist, limit=100)
        expected = {
            o
            for o in adjacency
            if o != artist
            and o not in adjacency[artist]
            and set(adjacency[o]) & set(adjacency[artist])
        }
        assert {r.artist_id for r in results} == expected
        for r in results:
            assert r.shared_count == len(set(adjacency[r.artist_id]) & set(adjacency[artist]))


@pytest.mark.parametrize("seed", range(25))
def test_taste_profile_matches_brute_force_on_random_graphs(seed: int) -> None:
    index = _random_index(seed)
    rng = random.Random(seed)
    members = rng.sample(sorted(index.adjacency), 10)
    result = taste.profile(index, dict.fromkeys(members, 1.0))
    assert result.artist_ids == tuple(members)
    member_set = set(members)
    reached = {b for a in members for b in index.adjacency[a]} - member_set
    assert result.collaborators_reached == len(reached)
    links = {a: set(index.adjacency[a]) & member_set for a in members}
    if result.central is not None:
        assert result.central[1] == max(len(v) for v in links.values())
    if result.cluster is not None:
        group = set(result.cluster.artist_ids)
        assert all(len(links[a] & group) >= result.cluster.min_links for a in group)
        # No larger k has a non-empty k-core.
        k = result.cluster.min_links + 1
        core = set(members)
        while True:
            drop = {a for a in core if len(links[a] & core) < k}
            if not drop:
                break
            core -= drop
        assert not core
    for c in result.connectors:
        assert c.artist_id not in member_set
        assert len(c.linked) >= 2
        assert all(m in index.adjacency[c.artist_id] for m in c.linked)
    pair = result.surprising_pair
    best = 0
    for a, b in itertools.combinations(members, 2):
        d = _distances(index, a).get(b)
        if d is not None and d <= taste.MAX_STEPS:
            best = max(best, d)
    if pair is None:
        assert best < 2
    else:
        assert pair.steps == best == _distances(index, pair.a)[pair.b]
    assert abs(sum(s.share for s in result.decades) - 1.0) < 1e-9


def test_taste_genre_mix_and_decades(index: BrowseIndex) -> None:
    result = taste.profile(index, {"a": 2.0, "b": 1.0, "prod": 1.0})
    assert result.artist_ids == ("a", "b", "prod")
    shares = {s.key: s.share for s in result.genres}
    assert shares == pytest.approx({"g-pop": (2.0 + 0.3) / 3.0, "g-rock": 0.7 / 3.0})
    assert result.unknown_genre_artists == 1
    decades = {s.key: s.artist_count for s in result.decades}
    assert decades["2010"] == 2  # b performs in 2010; prod is credited (producer) in 2010s
    assert result.central == ("prod", 2)
    assert taste.profile(index, {}).artist_ids == ()
    assert taste.play_weight(1) == 1.0


def test_step_track_prefers_unused_recordings_and_falls_back(index: BrowseIndex) -> None:
    first = step_track(index, "prod", "a", KINDS)
    assert first is not None
    assert first.recording_id == "r-a1"
    second = step_track(index, "prod", "a", KINDS, avoid=frozenset({"r-a1"}))
    assert second is not None
    assert second.recording_id == "r-a2"
    from_release = step_track(index, "d", "e", KINDS)
    assert from_release is not None
    assert (from_release.recording_id, from_release.release_id) == ("r-de", "rel-de")
    assert step_track(index, "e", "far", KINDS) is None  # a relation has no track
    assert step_track(index, "a", "x", KINDS) is None  # not connected
