"""Stories: short connection stories generated from the graph, each backed by credits.

Pure and deterministic: one catalog version always yields the same feed in the same
order. The server never writes prose. A story is a template message ID, the
artists it is about, a few numbers or names, and the credits that prove it, so
the client renders it in the viewer's language and every claim can be checked.

Kinds:

- ``SHARED_PRODUCER``: two well-known artists with no credit together who share a producer.
- ``TWO_STEPS``: two well-known artists exactly two connections apart, with the person between.
- ``SESSION_PLAYER``: a musician credited on many of one artist's songs.
- ``LABEL_MATES``: two well-known artists whose only connection is a shared label.
- ``SAME_SAMPLE``: one artist sampled by two others, years apart.
- ``SAMPLED``: one artist's song samples another (when no artist is sampled twice).

Stories use only artists with the most connections, so they are recognizable.
"""

from __future__ import annotations

import enum
import hashlib
import itertools
import random
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

from songnexus.core.graph.algorithms import weighted_degree
from songnexus.core.graph.explain import Explanation, explain_edge
from songnexus.core.graph.model import (
    DEFAULT_CATEGORIES,
    ArtistGraph,
    Edge,
    EdgeKind,
    SubjectType,
    kinds_for,
)
from songnexus.core.model import CONTRIBUTOR_ROLES

DEFAULT_KINDS = kinds_for(DEFAULT_CATEGORIES)
POPULAR_ARTISTS = 150
MAX_PER_KIND = 24
MAX_CREDITS = 12
MIN_SESSION_SONGS = 5
MIN_SAMPLE_GAP_YEARS = 10
SEED = "songnexus-stories-v1"
_CONTRIBUTOR_NAMES = frozenset(r.value for r in CONTRIBUTOR_ROLES)

Param = str | int


class StoryKind(enum.StrEnum):
    """Which template a story uses."""

    SHARED_PRODUCER = "shared_producer"
    TWO_STEPS = "two_steps"
    SESSION_PLAYER = "session_player"
    LABEL_MATES = "label_mates"
    SAME_SAMPLE = "same_sample"
    SAMPLED = "sampled"


MESSAGE_IDS = {
    StoryKind.SHARED_PRODUCER: "story.sharedProducer",  # {a} {b} {via}
    StoryKind.TWO_STEPS: "story.twoSteps",  # {a} {b} {via}
    StoryKind.SESSION_PLAYER: "story.sessionPlayer",  # {a} {via} {n} {role}
    StoryKind.LABEL_MATES: "story.labelMates",  # {a} {b} {label}
    StoryKind.SAME_SAMPLE: "story.sameSample",  # {a} {b} {via} {yearA} {yearB}
    StoryKind.SAMPLED: "story.sampled",  # {a} {via} {song}
}


@dataclass(frozen=True)
class Story:
    """One story.

    Attributes:
        id: Stable ID, a hash of the kind and the artists.
        kind: The template.
        parts: (role, artist ID) pairs; roles are the template's ``a``, ``b``, ``via``.
        params: Other template values (counts, years, a label or song name).
        credits: The credits that prove it, the strongest first.
        score: Ranking within its kind (higher first); not shown.
    """

    id: str
    kind: StoryKind
    parts: tuple[tuple[str, str], ...]
    params: tuple[tuple[str, Param], ...]
    credits: tuple[Explanation, ...]
    score: float

    @property
    def message_id(self) -> str:
        """The client message key."""
        return MESSAGE_IDS[self.kind]

    @property
    def artist_ids(self) -> tuple[str, ...]:
        """Every artist the story names."""
        return tuple(a for _, a in self.parts)


def _story_id(kind: StoryKind, parts: Sequence[tuple[str, str]]) -> str:
    text = kind.value + "|" + "|".join(f"{r}:{a}" for r, a in parts)
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def _make(
    kind: StoryKind,
    parts: Sequence[tuple[str, str]],
    credits: Sequence[Explanation],
    score: float,
    **params: Param,
) -> Story:
    return Story(
        _story_id(kind, parts),
        kind,
        tuple(parts),
        tuple(sorted(params.items())),
        tuple(credits[:MAX_CREDITS]),
        score,
    )


@dataclass(frozen=True)
class _Context:
    graph: ArtistGraph
    popular: tuple[str, ...]
    rank: dict[str, int]

    def explain(
        self, a: str, b: str, *kinds: EdgeKind, limit: int | None = None
    ) -> list[Explanation]:
        edge = self.graph.edge(a, b)
        if edge is None:
            return []
        wanted = frozenset(kinds) or DEFAULT_KINDS
        return explain_edge(self.graph, edge, a, wanted, limit=limit)

    def same_person(self, a: str, b: str) -> bool:
        return b in self.graph.other_identities([a])


def _context(graph: ArtistGraph) -> _Context:
    degree = weighted_degree(graph.adjacency(DEFAULT_KINDS))
    ranked = sorted(
        (a for a, n in graph.nodes.items() if n.detail_level != "stub"),
        key=lambda a: (-degree[a], a),
    )[:POPULAR_ARTISTS]
    return _Context(graph, tuple(ranked), {a: i for i, a in enumerate(ranked)})


def _genre_overlap(graph: ArtistGraph, a: str, b: str) -> float:
    nb = graph.nodes[b]
    return sum(min(g.share, nb.genre_share(g.genre_id)) for g in graph.nodes[a].genres)


def _shared_producer(ctx: _Context) -> list[Story]:
    produced: dict[str, set[str]] = defaultdict(set)  # producer -> well-known artists
    for edge in ctx.graph.edges.values():
        for ev in edge.evidence:
            if ev.kind is not EdgeKind.PRODUCED_FOR:
                continue
            producer, performer = (edge.a, edge.b) if ev.a_role == "producer" else (edge.b, edge.a)
            if performer in ctx.rank:
                produced[producer].add(performer)
    stories = []
    for producer in sorted(produced):
        artists = sorted(produced[producer], key=lambda a: ctx.rank[a])[:4]
        for a, b in itertools.combinations(artists, 2):
            if ctx.graph.edge(a, b) is not None or ctx.same_person(a, b):
                continue
            if producer in (a, b) or ctx.same_person(producer, a) or ctx.same_person(producer, b):
                continue
            first = ctx.explain(producer, a, EdgeKind.PRODUCED_FOR)
            second = ctx.explain(producer, b, EdgeKind.PRODUCED_FOR)
            if not first or not second:
                continue
            credits = [first[0], second[0], *first[1:3], *second[1:3]]
            score = -(ctx.rank[a] + ctx.rank[b]) - 5 * _genre_overlap(ctx.graph, a, b)
            stories.append(
                _make(
                    StoryKind.SHARED_PRODUCER,
                    [("a", a), ("b", b), ("via", producer)],
                    credits,
                    score,
                )
            )
            break  # the best pair for this producer is enough
    return stories


def _two_steps(ctx: _Context) -> list[Story]:
    adjacency = ctx.graph.adjacency(DEFAULT_KINDS)
    stories = []
    for a, b in itertools.combinations(ctx.popular[:100], 2):
        if b in adjacency[a] or ctx.same_person(a, b):
            continue
        common = sorted(
            (n for n in set(adjacency[a]) & set(adjacency[b]) if not ctx.same_person(n, a)),
            key=lambda n: (-min(adjacency[a][n], adjacency[b][n]), n),
        )
        if not common:
            continue
        via = common[0]
        first = ctx.explain(a, via, limit=2)
        second = ctx.explain(via, b, limit=2)
        if not first or not second:
            continue
        # Different scenes make the better story.
        score = -(ctx.rank[a] + ctx.rank[b]) / 2 - 40 * _genre_overlap(ctx.graph, a, b)
        stories.append(
            _make(
                StoryKind.TWO_STEPS,
                [("a", a), ("b", b), ("via", via)],
                [first[0], second[0], *first[1:], *second[1:]],
                score,
                steps=2,
            )
        )
    return stories


def _session_players(ctx: _Context) -> list[Story]:
    stories = []
    for a in ctx.popular:
        best: tuple[int, str, list[Explanation], str] | None = None
        for other in sorted(ctx.graph.neighbors[a]):
            edge = ctx.graph.edge(a, other)
            if ctx.same_person(a, other) or (edge and EdgeKind.MEMBER_OF in edge.kind_weight):
                continue  # a band member credited on their own band's songs is no story
            credits = [
                e
                for e in ctx.explain(a, other, EdgeKind.CONTRIBUTED_TO)
                if e.subject_type is SubjectType.RECORDING and e.to_role in _CONTRIBUTOR_NAMES
            ]
            songs = {e.subject_id for e in credits}
            if len(songs) < MIN_SESSION_SONGS:
                continue
            role = Counter(e.to_role for e in credits).most_common(1)[0][0]
            if best is None or len(songs) > best[0]:
                best = (len(songs), other, credits, role)
        if best is not None:
            n, other, credits, role = best
            stories.append(
                _make(
                    StoryKind.SESSION_PLAYER,
                    [("a", a), ("via", other)],
                    credits,
                    n - ctx.rank[a] / 10,
                    n=n,
                    role=role,
                )
            )
    return stories


def _label_mates(ctx: _Context) -> list[Story]:
    stories = []
    for a, b in itertools.combinations(ctx.popular, 2):
        edge: Edge | None = ctx.graph.edge(a, b)
        if edge is None or set(edge.kind_weight) != {EdgeKind.LABEL_MATES}:
            continue
        credits = ctx.explain(a, b, EdgeKind.LABEL_MATES)
        label = credits[0].subject_title if credits else None
        if not label:
            continue
        stories.append(
            _make(
                StoryKind.LABEL_MATES,
                [("a", a), ("b", b)],
                credits,
                -(ctx.rank[a] + ctx.rank[b]),
                label=label,
            )
        )
    return stories


def _samples(ctx: _Context) -> list[Story]:
    graph = ctx.graph
    sampled_by: dict[str, list[tuple[str, Explanation]]] = defaultdict(list)
    for edge in graph.edges.values():
        for ev in edge.evidence:
            if ev.kind is not EdgeKind.SAMPLED or ev.subject_type is not SubjectType.RECORDING:
                continue
            sampled, performer = (edge.a, edge.b) if ev.a_role == "sampled" else (edge.b, edge.a)
            for e in explain_edge(graph, edge, sampled, frozenset({EdgeKind.SAMPLED})):
                if e.subject_id == ev.subject_id:
                    sampled_by[sampled].append((performer, e))
                    break
    stories = []
    for sampled in sorted(sampled_by):
        uses = sorted(
            {(p, e.subject_id): (p, e) for p, e in sampled_by[sampled]}.values(),
            key=lambda pe: (graph.subject_years.get(pe[1].subject_id, 9999), pe[0]),
        )
        dated = [
            (p, e, graph.subject_years[e.subject_id])
            for p, e in uses
            if e.subject_id in graph.subject_years
        ]
        pair = next(
            (
                (x, y)
                for x, y in itertools.combinations(dated, 2)
                if x[0] != y[0] and y[2] - x[2] >= MIN_SAMPLE_GAP_YEARS
            ),
            None,
        )
        if pair is not None:
            (pa, ea, ya), (pb, eb, yb) = pair
            stories.append(
                _make(
                    StoryKind.SAME_SAMPLE,
                    [("a", pa), ("b", pb), ("via", sampled)],
                    [ea, eb],
                    10.0 + (yb - ya),
                    yearA=ya,
                    yearB=yb,
                )
            )
        elif uses:
            performer, e = uses[0]
            stories.append(
                _make(
                    StoryKind.SAMPLED,
                    [("a", performer), ("via", sampled)],
                    [e],
                    0.0,
                    song=e.subject_title or "",
                )
            )
    return stories


_GENERATORS = (
    _shared_producer,
    _two_steps,
    _session_players,
    _label_mates,
    _samples,
)


def generate(graph: ArtistGraph) -> tuple[Story, ...]:
    """Returns every story for the graph, mixed so no kind clusters, in a fixed order.

    The best ``MAX_PER_KIND`` of each kind are kept, ordered by a shuffle seeded by
    the catalog version, then interleaved round-robin across kinds.
    """
    ctx = _context(graph)
    by_kind: list[list[Story]] = []
    seen: set[str] = set()
    for generator in _GENERATORS:
        best = sorted(generator(ctx), key=lambda s: (-s.score, s.id))
        picked: list[Story] = []
        for story in best:
            # Spread across artists: one story per lead artist within a kind.
            lead = story.parts[0][1]
            key = f"{story.kind}:{lead}"
            if key in seen:
                continue
            seen.add(key)
            picked.append(story)
            if len(picked) == MAX_PER_KIND:
                break
        seed = int(hashlib.sha256(f"{SEED}:{graph.version}".encode()).hexdigest()[:16], 16)
        random.Random(seed).shuffle(picked)  # noqa: S311 - not security
        by_kind.append(picked)
    feed: list[Story] = []
    for row in itertools.zip_longest(*by_kind):
        feed.extend(s for s in row if s is not None)
    return tuple(feed)
