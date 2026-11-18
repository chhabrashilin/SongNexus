"""Friend paths and weekly movers: pure logic."""

from datetime import UTC, datetime

from songnexus.core import community as cc
from songnexus.core import friend_paths as fp

#  M1 - X - T1      M2 - Y - Z - T2      M1 - S (S also linked to T1)
ADJ: dict[str, dict[str, float]] = {}


def link(a: str, b: str) -> None:
    ADJ.setdefault(a, {})[b] = 1.0
    ADJ.setdefault(b, {})[a] = 1.0


for a, b in [
    ("M1", "X"),
    ("X", "T1"),
    ("M2", "Y"),
    ("Y", "Z"),
    ("Z", "T2"),
    ("M1", "S"),
    ("S", "T1"),
    ("SHARED", "M1"),
]:
    link(a, b)


def test_top_artists_prefer_the_chosen_top_five_then_plays() -> None:
    result = fp.top_artists(
        ["c"],
        [("a", 10), ("b", 50), ("a", 45), ("hidden", 999), ("unknown", 999)],
        known=lambda x: x != "unknown",
        hidden=frozenset({"hidden"}),
        limit=3,
    )
    assert result == ["c", "a", "b"]  # a: 55 plays across services


def test_connect_finds_shared_collaborators_and_shortest_paths() -> None:
    found = fp.connect(ADJ, ["M1", "M2", "SHARED"], ["T1", "T2", "SHARED"])
    assert found.shared == ("SHARED",)
    assert found.paths[0] in {("M1", "X", "T1"), ("M1", "S", "T1")}
    assert ("M2", "Y", "Z", "T2") in found.paths
    by_id = {c.artist_id: c for c in found.collaborators}
    assert by_id["X"].mine == ("M1",)
    assert by_id["X"].theirs == ("T1",)
    assert "M1" not in by_id  # a top artist itself is never a "collaborator"


def test_connect_respects_the_blocklist_predicate() -> None:
    found = fp.connect(ADJ, ["M1"], ["T1"], allowed=lambda n: n not in {"X", "S"})
    assert found.paths == ()
    assert found.collaborators == ()


def chart(ranks: list[str]) -> cc.Chart:
    rows = tuple(cc.ArtistRow(a, i, 10, 10, 3) for i, a in enumerate(ranks, start=1))
    return cc.Chart(20, rows, (), datetime(2026, 11, 16, tzinfo=UTC))


def test_weekly_movers() -> None:
    moved = cc.weekly_movers(chart(["new", "b", "a", "c"]), chart(["a", "b", "c", "gone"]))
    assert [(m.artist_id, m.places) for m in moved.rose] == []
    assert [(m.artist_id, m.rank, m.previous_rank, m.places) for m in moved.fell] == [
        ("a", 3, 1, 2),
        ("c", 4, 3, 1),
    ]
    assert [m.artist_id for m in moved.entered] == ["new"]
    assert [(m.artist_id, m.previous_rank) for m in moved.left] == [("gone", 4)]
    up = cc.weekly_movers(chart(["c", "a"]), chart(["a", "b", "c"]))
    assert [(m.artist_id, m.places) for m in up.rose] == [("c", 2)]
