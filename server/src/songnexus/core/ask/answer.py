"""Answers composed from our data only: graph searches and credits, never the model.

An answer is a message ID with parameters (the client words it in the
viewer's language), up to a few supporting rows with their evidence, and the
in-app page that shows the full answer. When a name doesn't resolve, the
answer says so and offers the alternatives instead of guessing.
"""

from __future__ import annotations

import itertools
from collections.abc import Collection
from dataclasses import dataclass, field
from typing import Protocol
from urllib.parse import urlencode

from songnexus.core.ask.intents import CreditRole, Intent, Interpretation, SongRef
from songnexus.core.ask.resolve import (
    Candidate,
    Resolved,
    Status,
    plausible,
    resolve_artist,
    resolve_genre,
    resolve_song,
)
from songnexus.core.graph import collaborations as collab
from songnexus.core.graph.algorithms import bidirectional_bfs_path, dijkstra_path
from songnexus.core.graph.compare import compare
from songnexus.core.graph.explain import Explanation, explain_edge, explain_path
from songnexus.core.graph.filters import NodeFilter
from songnexus.core.graph.model import DEFAULT_CATEGORIES, ArtistGraph, kinds_for
from songnexus.core.search import EntityType, MatchType, SearchIndex
from songnexus.core.text import normalize

MAX_PATH_STEPS = 6
PAIR = 2
MAX_ROWS = 5
MAX_NAMES = 3
KINDS = kinds_for(DEFAULT_CATEGORIES)

ParamValue = str | int | list[str]


@dataclass(frozen=True)
class RecordingFacts:
    """What the answer needs about one recording."""

    recording_id: str
    title: str
    credits: tuple[tuple[str, str], ...]  # (artist ID, role) in credit order


class Catalog(Protocol):
    """Recording data that lives outside the graph (the database)."""

    def recording(self, recording_id: str) -> RecordingFacts | None:
        """Returns a recording's title and credits, or None when unknown."""
        ...

    def song_similarity(self, a: str, b: str) -> float | None:
        """Returns the explained sound similarity of two recordings (None without data)."""
        ...


@dataclass(frozen=True)
class Row:
    """A supporting result: an artist or a song, with why it is here."""

    artist_id: str | None = None
    recording: Candidate | None = None
    role: str | None = None
    count: int | None = None
    first_year: int | None = None
    last_year: int | None = None
    explanations: tuple[Explanation, ...] = ()
    # A credit row is backed by this recording's own sources.
    credited_on: str | None = None


@dataclass(frozen=True)
class Answer:
    """The composed answer."""

    intent: Intent
    message_id: str
    params: dict[str, ParamValue] = field(default_factory=dict)
    entities: tuple[Resolved, ...] = ()
    rows: tuple[Row, ...] = ()
    destination: str | None = None
    genre: tuple[str, str] | None = None  # (genre ID, name) when narrowed by genre


@dataclass(frozen=True)
class Context:
    """Everything an answer may read."""

    graph: ArtistGraph
    index: SearchIndex
    catalog: Catalog
    blocked: frozenset[str] = frozenset()
    choices: Collection[str] = ()

    @property
    def node_filter(self) -> NodeFilter:
        """Blocks apply to everything in between; endpoints are the viewer's choice."""
        return NodeFilter(blocked=self.blocked)

    def name(self, artist_id: str) -> str:
        """Returns an artist's display name."""
        return self.graph.nodes[artist_id].name


def _query(path: str, **params: str | None) -> str:
    kept = {k: v for k, v in params.items() if v is not None}
    return f"{path}?{urlencode(kept)}" if kept else path


def _names(ctx: Context, artist_ids: list[str]) -> dict[str, ParamValue]:
    return {
        "names": [ctx.name(a) for a in artist_ids[:MAX_NAMES]],
        "more": max(0, len(artist_ids) - MAX_NAMES),
    }


def _problem(intent: Intent, entities: tuple[Resolved, ...]) -> Answer | None:
    """The answer when a name did not resolve: not found, or which one did you mean."""
    for entity in entities:
        if entity.status is Status.NOT_FOUND:
            return Answer(intent, "ask.answer.notFound", {"name": entity.mention}, entities)
    for entity in entities:
        if entity.status is Status.AMBIGUOUS:
            return Answer(intent, "ask.answer.ambiguous", {"name": entity.mention}, entities)
    return None


def _artists(ctx: Context, mentions: tuple[str, ...]) -> tuple[Resolved, ...]:
    return tuple(
        resolve_artist(ctx.index, m, choices=ctx.choices, exclude=ctx.blocked) for m in mentions
    )


def _song(ctx: Context, ref: SongRef) -> tuple[Resolved, ...]:
    """Resolves a song, and its artist when named. Returns (song,) or (artist, song)."""
    if ref.artist is None:
        return (resolve_song(ctx.index, ref.title, choices=ctx.choices),)
    artist = resolve_artist(ctx.index, ref.artist, choices=ctx.choices, exclude=ctx.blocked)
    song = resolve_song(ctx.index, ref.title, artist, choices=ctx.choices)
    if artist.status is not Status.MATCHED or song.status is Status.NOT_FOUND:
        # "Stand by Me" is a title, not "Stand" by "Me".
        whole = resolve_song(ctx.index, f"{ref.title} by {ref.artist}", choices=ctx.choices)
        if whole.status is not Status.NOT_FOUND and _exact_title(whole):
            return (whole,)
    return (artist, song)


def _exact_title(resolved: Resolved) -> bool:
    return resolved.match is not None and normalize(resolved.match.name) == normalize(
        resolved.mention
    )


# ---------------------------------------------------------------------------
# Intents
# ---------------------------------------------------------------------------


def _path(ctx: Context, it: Interpretation) -> Answer:
    entities = _artists(ctx, it.artists)
    if problem := _problem(Intent.FIND_PATH, entities):
        return problem
    a, b = (e.entity_id for e in entities)
    assert a is not None
    assert b is not None
    mode = "STRONGEST_LINKS" if it.strongest else "FEWEST_STEPS"
    destination = _query("/six-degrees", **{"from": a, "to": b, "mode": mode})
    if a == b:
        return Answer(Intent.FIND_PATH, "ask.answer.sameArtist", {"a": ctx.name(a)}, entities)
    adjacency = ctx.graph.adjacency(KINDS)
    allowed = ctx.node_filter.predicate(ctx.graph)
    search = dijkstra_path if it.strongest else bidirectional_bfs_path
    result = search(adjacency, a, b, max_depth=MAX_PATH_STEPS, allowed=allowed)
    params: dict[str, ParamValue] = {"a": ctx.name(a), "b": ctx.name(b)}
    if result.path is None:
        message = "ask.answer.pathLimit" if result.truncated else "ask.answer.pathNone"
        params["max"] = MAX_PATH_STEPS
        return Answer(Intent.FIND_PATH, message, params, entities, destination=destination)
    steps = explain_path(ctx.graph, result.path, KINDS, per_step=1)
    params["steps"] = len(result.path) - 1
    rows = tuple(
        Row(artist_id=v, explanations=tuple(explanations))
        for (_, v), explanations in zip(itertools.pairwise(result.path), steps, strict=True)
    )
    message = "ask.answer.pathDirect" if len(result.path) == PAIR else "ask.answer.path"
    return Answer(Intent.FIND_PATH, message, params, entities, rows, destination)


def _compare_artists(ctx: Context, it: Interpretation) -> Answer:
    entities = _artists(ctx, it.artists)
    if any(e.status is not Status.MATCHED for e in entities):
        # "HUMBLE. vs DNA." without quotes: two songs, not two artists.
        songs = tuple(resolve_song(ctx.index, m, choices=ctx.choices) for m in it.artists)
        if all(s.status is Status.MATCHED and _exact_title(s) for s in songs):
            return _compare_resolved_songs(ctx, songs)
    if problem := _problem(Intent.COMPARE_ARTISTS, entities):
        return problem
    a, b = (e.entity_id for e in entities)
    assert a is not None
    assert b is not None
    destination = _query("/compare", a=a, b=b)
    if a == b:
        return Answer(Intent.COMPARE_ARTISTS, "ask.answer.sameArtist", {"a": ctx.name(a)}, entities)
    result = compare(ctx.graph, a, b, KINDS, node_filter=ctx.node_filter, max_depth=MAX_PATH_STEPS)
    adjacency = ctx.graph.adjacency(KINDS)
    mutual = sorted(
        result.mutual_collaborators,
        key=lambda n: (-(adjacency[a][n] + adjacency[b][n]), ctx.name(n), n),
    )
    rows = []
    for other in mutual[:MAX_ROWS]:
        edge = ctx.graph.edge(a, other)
        explanations = tuple(explain_edge(ctx.graph, edge, a, KINDS, limit=1)) if edge else ()
        rows.append(Row(artist_id=other, explanations=explanations))
    params: dict[str, ParamValue] = {
        "a": ctx.name(a),
        "b": ctx.name(b),
        "mutual": len(mutual),
        "genres": [g.name for g in result.shared_genres[:MAX_NAMES]],
        "steps": len(result.path.path) - 1 if result.path.path else -1,
    }
    return Answer(
        Intent.COMPARE_ARTISTS, "ask.answer.compare", params, entities, tuple(rows), destination
    )


def _compare_songs(ctx: Context, it: Interpretation) -> Answer:
    resolved = [_song(ctx, ref) for ref in it.songs]
    entities = tuple(e for group in resolved for e in group)
    if problem := _problem(Intent.COMPARE_SONGS, entities):
        return problem
    return _compare_resolved_songs(ctx, (resolved[0][-1], resolved[1][-1]), entities)


def _compare_resolved_songs(
    ctx: Context, songs: tuple[Resolved, ...], entities: tuple[Resolved, ...] | None = None
) -> Answer:
    entities = entities or songs
    a, b = (s.entity_id for s in songs)
    assert a is not None
    assert b is not None
    facts = [ctx.catalog.recording(a), ctx.catalog.recording(b)]
    if facts[0] is None or facts[1] is None:
        return Answer(
            Intent.COMPARE_SONGS, "ask.answer.notFound", {"name": songs[0].mention}, entities
        )

    def people(f: RecordingFacts) -> dict[str, str]:
        found: dict[str, str] = {}
        for artist_id, role in f.credits:
            if artist_id in ctx.graph.nodes and artist_id not in ctx.blocked:
                found.setdefault(artist_id, role)
        return found

    on_a, on_b = people(facts[0]), people(facts[1])
    shared = sorted(set(on_a) & set(on_b), key=lambda x: (ctx.name(x), x))
    similarity = ctx.catalog.song_similarity(a, b)
    params: dict[str, ParamValue] = {
        "a": facts[0].title,
        "b": facts[1].title,
        "shared": len(shared),
        "similarity": -1 if similarity is None else round(similarity * 100),
    }
    rows = tuple(Row(artist_id=x, role=on_a[x], credited_on=a) for x in shared[:MAX_ROWS])
    return Answer(
        Intent.COMPARE_SONGS,
        "ask.answer.compareSongs",
        params,
        entities,
        rows,
        _query("/compare/songs", a=a, b=b),
    )


_ROLE = {
    CreditRole.PRODUCER: "producer",
    CreditRole.FEATURED: "featured",
    CreditRole.PERFORMER: "primary",
}


def _song_credits(ctx: Context, it: Interpretation) -> Answer:
    role = it.credit_role or CreditRole.ALL
    (ref,) = it.songs
    entities = _song(ctx, ref)
    song = entities[-1]
    # "Who produced Kendrick Lamar?" names an artist, not a song.
    if (
        (song.status is not Status.MATCHED or not _exact_title(song))
        and ref.artist is None
        and role is not CreditRole.ALL
    ):
        artist = resolve_artist(ctx.index, ref.title, choices=ctx.choices, exclude=ctx.blocked)
        if artist.status is Status.MATCHED and artist.match and _exact_title(artist):
            return _collaborators(ctx, _as_collaborators(it, role), (artist,))
    if problem := _problem(Intent.SONG_CREDITS, entities):
        return problem
    recording_id = song.entity_id
    assert recording_id is not None
    facts = ctx.catalog.recording(recording_id)
    if facts is None:
        return Answer(Intent.SONG_CREDITS, "ask.answer.notFound", {"name": ref.title}, entities)
    wanted = _ROLE.get(role)
    credited: dict[str, str] = {}
    for artist_id, credit_role in facts.credits:
        if artist_id not in ctx.graph.nodes or artist_id in ctx.blocked:
            continue
        if wanted is None or credit_role == wanted:
            credited.setdefault(artist_id, credit_role)
    ids = list(credited)
    params: dict[str, ParamValue] = {"song": facts.title, "count": len(ids), **_names(ctx, ids)}
    message = f"ask.answer.song.{role.value}" + ("" if ids else ".none")
    rows = tuple(
        Row(artist_id=x, role=credited[x], credited_on=recording_id) for x in ids[:MAX_ROWS]
    )
    return Answer(Intent.SONG_CREDITS, message, params, entities, rows, f"/song/{recording_id}")


def _as_collaborators(it: Interpretation, role: CreditRole) -> Interpretation:
    if role is CreditRole.PRODUCER:
        return Interpretation(
            Intent.COLLABORATORS,
            artists=(it.songs[0].title,),
            collaboration_type=collab.CollaborationType.PRODUCTION,
            direction=collab.ProductionDirection.PRODUCED_BY,
            source=it.source,
        )
    return Interpretation(
        Intent.COLLABORATORS,
        artists=(it.songs[0].title,),
        collaboration_type=collab.CollaborationType.FEATURE,
        source=it.source,
    )


@dataclass
class _Merged:
    subjects: set[str] = field(default_factory=set)
    years: list[int] = field(default_factory=list)


def _collaborators(
    ctx: Context, it: Interpretation, entities: tuple[Resolved, ...] | None = None
) -> Answer:
    entities = entities or _artists(ctx, it.artists)
    if problem := _problem(Intent.COLLABORATORS, entities):
        return problem
    artist = entities[0].entity_id
    assert artist is not None
    genre = None
    node_filter = ctx.node_filter
    if it.genre:
        genre = resolve_genre(ctx.graph, it.genre)
        if genre is None:
            return Answer(
                Intent.COLLABORATORS, "ask.answer.genreNotFound", {"genre": it.genre}, entities
            )
        node_filter = NodeFilter(
            genre_ids=ctx.graph.with_subgenres({genre[0]}),
            include_unknown_genre=False,
            blocked=ctx.blocked,
        )
    years = (
        None
        if it.start_year is None and it.end_year is None
        else collab.YearRange(it.start_year, it.end_year)
    )
    types = [it.collaboration_type] if it.collaboration_type else list(collab.CollaborationType)
    direction = (
        it.direction if it.collaboration_type is collab.CollaborationType.PRODUCTION else None
    )
    merged: dict[str, _Merged] = {}
    evidence_kinds = frozenset().union(*(collab.TYPE_KINDS[t] for t in types))
    for collaboration_type in types:
        for item in collab.collaborations(
            ctx.graph, artist, collaboration_type, node_filter, direction=direction, years=years
        ):
            entry = merged.setdefault(item.artist_id, _Merged())
            entry.subjects.update(e.subject_id for e in item.evidence)
            entry.years.extend(y for y in (item.first_year, item.last_year) if y is not None)
    ordered = sorted(merged, key=lambda x: (-len(merged[x].subjects), ctx.name(x), x))
    rows = []
    for other in ordered[:MAX_ROWS]:
        entry = merged[other]
        edge = ctx.graph.edge(artist, other)
        explanations = [
            e
            for e in (explain_edge(ctx.graph, edge, artist, evidence_kinds) if edge else [])
            if e.subject_id in entry.subjects
        ][:1]
        rows.append(
            Row(
                artist_id=other,
                count=len(entry.subjects),
                first_year=min(entry.years, default=None),
                last_year=max(entry.years, default=None),
                explanations=tuple(explanations),
            )
        )
    variant = (
        "ANY"
        if it.collaboration_type is None
        else direction.value
        if direction is not None
        else it.collaboration_type.value
    )
    params: dict[str, ParamValue] = {
        "artist": ctx.name(artist),
        "count": len(ordered),
        **_names(ctx, ordered),
    }
    message = f"ask.answer.collab.{variant}" + ("" if ordered else ".none")
    query: dict[str, str | None] = {
        "type": it.collaboration_type.value if it.collaboration_type else None,
        "direction": direction.value if direction else None,
        "from": str(it.start_year) if it.start_year else None,
        "to": str(it.end_year) if it.end_year else None,
        "genres": f"genres/{genre[0]}" if genre else None,
        "unknown": "0" if genre else None,
    }
    return Answer(
        Intent.COLLABORATORS,
        message,
        params,
        entities,
        tuple(rows),
        _query(f"/artist/{artist}/collaborations", **query),
        genre,
    )


def _connections(ctx: Context, it: Interpretation) -> Answer:
    entities = _artists(ctx, it.artists)
    if problem := _problem(Intent.CONNECTIONS, entities):
        return problem
    artist = entities[0].entity_id
    assert artist is not None
    adjacency = ctx.graph.adjacency(KINDS)
    neighbors = sorted(
        (n for n in adjacency[artist] if n not in ctx.blocked),
        key=lambda n: (-adjacency[artist][n], ctx.name(n), n),
    )
    rows = []
    for other in neighbors[:MAX_ROWS]:
        edge = ctx.graph.edge(artist, other)
        explanations = tuple(explain_edge(ctx.graph, edge, artist, KINDS, limit=1)) if edge else ()
        rows.append(Row(artist_id=other, explanations=explanations))
    params: dict[str, ParamValue] = {
        "artist": ctx.name(artist),
        "count": len(neighbors),
        **_names(ctx, neighbors),
    }
    message = "ask.answer.connections" + ("" if neighbors else ".none")
    return Answer(Intent.CONNECTIONS, message, params, entities, tuple(rows), f"/explore/{artist}")


def _lookup(ctx: Context, it: Interpretation) -> Answer:
    text = it.text or ""
    hits = ctx.index.search(
        text, limit=MAX_ROWS, entity_types=frozenset({EntityType.ARTIST, EntityType.RECORDING})
    )
    hits = [
        h
        for h in hits
        if (h.entity_id not in ctx.blocked or h.match_type is MatchType.EXACT)
        and plausible(text, h)
    ]
    if not hits:
        return Answer(Intent.LOOKUP, "ask.answer.nothing", {"query": text})
    top = hits[0]
    entity = Resolved(
        text,
        top.entity_type,
        Status.MATCHED,
        Candidate(top.entity_type, top.entity_id, top.name, top.subtitle),
    )
    rows = tuple(
        Row(artist_id=h.entity_id)
        if h.entity_type is EntityType.ARTIST and h.entity_id in ctx.graph.nodes
        else Row(recording=Candidate(h.entity_type, h.entity_id, h.name, h.subtitle))
        for h in hits
        if h.entity_type is EntityType.RECORDING or h.entity_id in ctx.graph.nodes
    )
    is_song = top.entity_type is EntityType.RECORDING
    return Answer(
        Intent.LOOKUP,
        "ask.answer.lookup.song" if is_song else "ask.answer.lookup.artist",
        {"name": top.name},
        (entity,),
        rows,
        f"/song/{top.entity_id}" if is_song else f"/artist/{top.entity_id}",
    )


_HANDLERS = {
    Intent.FIND_PATH: _path,
    Intent.COMPARE_ARTISTS: _compare_artists,
    Intent.COMPARE_SONGS: _compare_songs,
    Intent.SONG_CREDITS: _song_credits,
    Intent.COLLABORATORS: _collaborators,
    Intent.CONNECTIONS: _connections,
    Intent.LOOKUP: _lookup,
}


def answer(ctx: Context, interpretation: Interpretation | None) -> Answer:
    """Answers an interpretation from the catalog (UNKNOWN when there is none)."""
    if interpretation is None or not interpretation.is_complete():
        return Answer(Intent.UNKNOWN, "ask.answer.unknown")
    handler = _HANDLERS.get(interpretation.intent)
    if handler is None:
        return Answer(Intent.UNKNOWN, "ask.answer.unknown")
    return handler(ctx, interpretation)


def subjects_of(rows: Collection[Row]) -> list[tuple[str, str]]:
    """(subject type, subject ID) pairs behind the rows' evidence, for a source lookup."""
    return sorted({(e.subject_type.value, e.subject_id) for r in rows for e in r.explanations})


def artist_ids(result: Answer) -> list[str]:
    """Every artist an answer mentions (rows and evidence), for display names."""
    found: dict[str, None] = {}
    for row in result.rows:
        if row.artist_id:
            found[row.artist_id] = None
        for e in row.explanations:
            found[e.from_artist] = None
            found[e.to_artist] = None
    for entity in result.entities:
        if entity.entity_type is EntityType.ARTIST:
            for c in (entity.match, *entity.alternatives):
                if c is not None:
                    found[c.entity_id] = None
    return list(found)
