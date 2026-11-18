"""Playlist analysis, checked against brute force on random graphs."""

import itertools

from hypothesis import given, settings
from hypothesis import strategies as st

from songnexus.core.graph.playlist import analyze_playlist
from tests.core.graph.test_algorithms import Adj, graphs


@settings(max_examples=150, deadline=None)
@given(graphs(), st.data())
def test_cohesion_matches_brute_force(adj: Adj, data: st.DataObject) -> None:
    nodes = sorted(adj)
    members = data.draw(
        st.lists(st.sampled_from(nodes), unique=True, min_size=0, max_size=len(nodes))
    )
    blocked = data.draw(st.frozensets(st.sampled_from(nodes)))

    def allowed(node: str) -> bool:
        return node not in blocked

    result = analyze_playlist(adj, members, {}, allowed=allowed)

    expected = 0
    for a, b in itertools.combinations(members, 2):
        direct = b in adj[a]
        via = any(x in adj[b] and allowed(x) for x in adj[a])
        expected += direct or via
    assert result.pairs == len(members) * (len(members) - 1) // 2
    assert result.pairs_within_two == expected


@settings(max_examples=100, deadline=None)
@given(graphs(), st.data())
def test_connectors_and_thread(adj: Adj, data: st.DataObject) -> None:
    nodes = sorted(adj)
    members = data.draw(
        st.lists(st.sampled_from(nodes), unique=True, min_size=2, max_size=len(nodes))
    )
    result = analyze_playlist(adj, members, {})
    member_set = set(members)
    for connector in result.connectors:
        assert connector.artist_id not in member_set
        assert len(connector.linked) >= 2
        assert all(m in adj[connector.artist_id] for m in connector.linked)
        assert connector.score == sum(adj[connector.artist_id][m] for m in connector.linked)
    assert [c.score for c in result.connectors] == sorted(
        (c.score for c in result.connectors), reverse=True
    )
    # The thread starts at the first artist, visits members in order, and every
    # step is a real connection except the counted breaks.
    assert result.thread[0] == members[0]
    gaps = sum(1 for a, b in itertools.pairwise(result.thread) if b not in adj[a])
    assert gaps == result.thread_breaks
    # The first 25 members appear on the thread in playlist order (a subsequence).
    remaining = iter(result.thread)
    assert all(any(node == member for node in remaining) for member in members[:25])
    for a, b, strength in result.links:
        assert a in member_set
        assert b in member_set
        assert adj[a][b] == strength


def test_empty_and_single() -> None:
    adj: Adj = {"a": {"b": 1.0}, "b": {"a": 1.0}}
    assert analyze_playlist(adj, [], {}).cohesion is None
    assert analyze_playlist(adj, ["a"], {}).cohesion is None
    assert analyze_playlist(adj, ["a", "b"], {}).cohesion == 1.0
    assert analyze_playlist(adj, ["a", "unknown"], {}).pairs == 0
