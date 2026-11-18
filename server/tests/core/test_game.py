"""The daily puzzle's rules, checked on random graphs."""

from datetime import date, timedelta

import networkx as nx
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from songnexus.core.game import (
    HINT_SIZE,
    LAUNCH_DAY,
    MAX_PAR,
    MIN_PAR,
    candidate_pairs,
    hint,
    puzzle_for,
    steps_to_target,
)
from tests.core.graph.test_algorithms import Adj, graphs, to_nx


@settings(max_examples=100, deadline=None)
@given(graphs())
def test_every_candidate_pair_is_fair(adj: Adj) -> None:
    graph = to_nx(adj)
    pool = sorted(adj)
    for a, b, par in candidate_pairs(adj, pool):
        assert a < b
        assert MIN_PAR <= par <= MAX_PAR
        assert nx.shortest_path_length(graph, a, b) == par
    # Complete: no fair pair is missing.
    expected = {
        (a, b)
        for i, a in enumerate(pool)
        for b in pool[i + 1 :]
        if nx.has_path(graph, a, b) and MIN_PAR <= nx.shortest_path_length(graph, a, b) <= MAX_PAR
    }
    assert {(a, b) for a, b, _ in candidate_pairs(adj, pool)} == expected


def chain(n: int) -> Adj:
    adj: Adj = {f"n{i}": {} for i in range(n)}
    for i in range(n - 1):
        adj[f"n{i}"][f"n{i + 1}"] = adj[f"n{i + 1}"][f"n{i}"] = 1.0
    return adj


def test_daily_puzzle_is_deterministic_and_numbered() -> None:
    pairs = candidate_pairs(chain(8), list(chain(8)))
    first = puzzle_for(LAUNCH_DAY, pairs)
    assert first.number == 1
    assert puzzle_for(LAUNCH_DAY, pairs) == first
    later = [puzzle_for(LAUNCH_DAY + timedelta(days=d), pairs) for d in range(60)]
    assert {(p.start, p.target) for p in later} != {(first.start, first.target)}  # varies by day
    assert all(MIN_PAR <= p.par <= MAX_PAR for p in later)


def test_no_puzzle_before_launch_or_without_pairs() -> None:
    with pytest.raises(ValueError, match="launch"):
        puzzle_for(LAUNCH_DAY - timedelta(days=1), [("a", "b", 3)])
    with pytest.raises(ValueError, match="no fair"):
        puzzle_for(date(2027, 1, 1), [])


def test_steps_to_target() -> None:
    adj = chain(12)
    assert steps_to_target(adj, "n3", "n0") == 3
    assert steps_to_target(adj, "n11", "n0") is None  # 11 > MAX_REMAINING


@settings(max_examples=150, deadline=None)
@given(graphs(), st.data())
def test_hints_include_a_closest_step_and_are_stable(adj: Adj, data: st.DataObject) -> None:
    nodes = sorted(adj)
    current = data.draw(st.sampled_from(nodes))
    target = data.draw(st.sampled_from(nodes))
    options = hint(adj, current, target)
    assert options == hint(adj, current, target)  # same for every player
    graph = to_nx(adj)
    has_route = current != target and nx.has_path(graph, current, target)
    assert len(options) == (min(HINT_SIZE, len(adj[current])) if has_route else 0)
    assert len(set(options)) == len(options)
    assert all(o in adj[current] for o in options)
    if options:
        graph = to_nx(adj)
        lengths = nx.single_source_shortest_path_length(graph, target)
        best = min(lengths.get(n, 99) for n in adj[current])
        assert any(lengths.get(o, 99) == best for o in options)


@pytest.mark.parametrize("cycle", [0, 1, 2])
def test_no_unordered_pair_repeats_within_a_cycle(cycle: int) -> None:
    pairs = candidate_pairs(chain(12), list(chain(12)))
    puzzles = [
        puzzle_for(LAUNCH_DAY + timedelta(days=cycle * len(pairs) + i), pairs)
        for i in range(len(pairs))
    ]
    assert {frozenset((p.start, p.target)) for p in puzzles} == {
        frozenset((a, b)) for a, b, _ in pairs
    }
    assert len({frozenset((p.start, p.target)) for p in puzzles}) == len(pairs)


def test_no_hint_when_disconnected_solved_or_all_closer_artists_blocked() -> None:
    adj = chain(12)
    adj["isolated"] = {}
    assert hint(adj, "n0", "isolated") == []
    assert hint(adj, "n0", "n0") == []
    assert hint(adj, "n5", "n0", allowed=lambda n: n != "n4") == []
    assert "n1" in hint(adj, "n0", "n11")  # outside the feedback depth cap


def test_hints_skip_blocked_artists() -> None:
    adj: Adj = {"c": {"a": 1, "b": 1, "x": 1}, "a": {"c": 1}, "b": {"c": 1}, "x": {"c": 1}}
    assert "x" not in hint(adj, "c", "a", allowed=lambda n: n != "x")
