"""Names in a question to catalog entities, with alternatives instead of silent guesses.

A name is matched when one candidate clearly leads (an exact name, or a
partial match well ahead of the next); otherwise it is ambiguous and the
person picks ("Did you mean …"). A pick comes back as a resource name in
``choices`` and wins over the text.
"""

from __future__ import annotations

import enum
from collections.abc import Collection
from dataclasses import dataclass

from songnexus.core.graph.model import ArtistGraph
from songnexus.core.search import EntityType, MatchType, SearchHit, SearchIndex
from songnexus.core.text import normalize, string_similarity

# Ranking scores closer than this are a tie.
TIE_MARGIN = 0.02
# A non-exact top hit must lead the next by this much to be taken.
PARTIAL_LEAD = 0.05
MAX_ALTERNATIVES = 3
GENRE_SIMILARITY = 0.85
# A fuzzy hit this close to the name (typos, spacing) can answer a question.
FUZZY_SIMILARITY = 0.75


class Status(enum.StrEnum):
    """How a name resolved."""

    MATCHED = "MATCHED"
    AMBIGUOUS = "AMBIGUOUS"
    NOT_FOUND = "NOT_FOUND"


@dataclass(frozen=True)
class Candidate:
    """A catalog entity a name might mean."""

    entity_type: EntityType
    entity_id: str
    name: str
    subtitle: str = ""


@dataclass(frozen=True)
class Resolved:
    """One name from the question and what it refers to."""

    mention: str
    entity_type: EntityType
    status: Status
    match: Candidate | None = None
    alternatives: tuple[Candidate, ...] = ()

    @property
    def entity_id(self) -> str | None:
        """The matched entity, or None."""
        return self.match.entity_id if self.match and self.status is Status.MATCHED else None


def _candidate(hit: SearchHit) -> Candidate:
    return Candidate(hit.entity_type, hit.entity_id, hit.name, hit.subtitle)


def plausible(mention: str, hit: SearchHit) -> bool:
    """Returns whether a hit is a reasonable reading of a name, not just a distant fuzzy match.

    Search is generous so a person typing sees something; an answer is not, so
    "Pray For Me" never turns into "Army of Me".
    """
    if hit.match_type is not MatchType.FUZZY:
        return True
    return string_similarity(normalize(mention), normalize(hit.matched_on)) >= FUZZY_SIMILARITY


def _decide(
    mention: str,
    entity_type: EntityType,
    hits: list[SearchHit],
    choices: Collection[str],
) -> Resolved:
    chosen = next((h for h in hits if h.entity_id in choices), None)
    hits = [h for h in hits if plausible(mention, h)]
    if chosen is not None:
        others = tuple(_candidate(h) for h in hits if h is not chosen)[:MAX_ALTERNATIVES]
        return Resolved(mention, entity_type, Status.MATCHED, _candidate(chosen), others)
    if not hits:
        return Resolved(mention, entity_type, Status.NOT_FOUND)
    top = hits[0]
    rest = hits[1:]
    runner_up = rest[0] if rest else None
    # A clear match lists only others with the very same name (several artists are "Drake").
    homonyms = tuple(_candidate(h) for h in rest if normalize(h.name) == normalize(top.name))[
        :MAX_ALTERNATIVES
    ]
    alternatives = (_candidate(top), *(_candidate(h) for h in rest))[: MAX_ALTERNATIVES + 1]
    if top.match_type is MatchType.EXACT or top.match_type is MatchType.EPONYMOUS:
        tied = (
            runner_up is not None
            and runner_up.match_type is MatchType.EXACT
            and top.score - runner_up.score < TIE_MARGIN
        )
        status = Status.AMBIGUOUS if tied else Status.MATCHED
        return Resolved(
            mention, entity_type, status, _candidate(top), alternatives if tied else homonyms
        )
    if runner_up is None or top.score - runner_up.score >= PARTIAL_LEAD:
        return Resolved(mention, entity_type, Status.MATCHED, _candidate(top), homonyms)
    return Resolved(mention, entity_type, Status.AMBIGUOUS, _candidate(top), alternatives)


def resolve_artist(
    index: SearchIndex,
    mention: str,
    *,
    choices: Collection[str] = (),
    exclude: frozenset[str] = frozenset(),
) -> Resolved:
    """Resolves an artist name. Blocked artists (``exclude``) match only by exact name."""
    hits = index.search(
        mention, limit=MAX_ALTERNATIVES + 2, entity_types=frozenset({EntityType.ARTIST})
    )
    hits = [h for h in hits if h.entity_id not in exclude or h.match_type is MatchType.EXACT]
    return _decide(mention, EntityType.ARTIST, hits, choices)


def resolve_song(
    index: SearchIndex,
    title: str,
    artist: Resolved | None = None,
    *,
    choices: Collection[str] = (),
) -> Resolved:
    """Resolves a song title, narrowed to an artist's songs when one is given.

    The same song often exists as several recordings (single, album, remaster)
    by the same artist; those are one song, so only competing artists make a
    title ambiguous.
    """
    hits = index.search(title, limit=20, entity_types=frozenset({EntityType.RECORDING}))
    if artist is not None and artist.match is not None:
        name = normalize(artist.match.name)
        by_artist = [h for h in hits if name and name in normalize(h.subtitle)]
        hits = by_artist or hits
    deduped: list[SearchHit] = []
    seen: set[tuple[str, str]] = set()
    for hit in hits:
        key = (normalize(hit.name), _artists_of(hit.subtitle))
        if key not in seen:
            seen.add(key)
            deduped.append(hit)
    return _decide(title, EntityType.RECORDING, deduped[: MAX_ALTERNATIVES + 2], choices)


def _artists_of(subtitle: str) -> str:
    return normalize(subtitle.split(" · ", 1)[0])


def resolve_genre(graph: ArtistGraph, mention: str) -> tuple[str, str] | None:
    """Returns (genre ID, name) for a genre name in the served vocabulary, or None."""
    wanted = normalize(mention)
    if not wanted:
        return None
    carried = graph.genre_artist_counts()
    best: tuple[float, int, str] | None = None
    for genre_id, name in graph.genre_names.items():
        if genre_id not in carried:
            continue
        key = normalize(name)
        similarity = (
            1.0
            if key == wanted or key.replace(" ", "") == wanted.replace(" ", "")
            else (string_similarity(wanted, key, floor=GENRE_SIMILARITY))
        )
        if similarity >= GENRE_SIMILARITY:
            score = (similarity, carried[genre_id][1], genre_id)
            if best is None or score > best:
                best = score
    if best is None:
        return None
    return best[2], graph.genre_names[best[2]]


def genre_vocabulary(graph: ArtistGraph) -> frozenset[str]:
    """Normalized names of genres any artist carries (for the parser)."""
    carried = graph.genre_artist_counts()
    return frozenset(normalize(n) for g, n in graph.genre_names.items() if g in carried)
