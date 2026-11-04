"""An artist's collaborations, grouped the way listeners think about them (US-16).

Counts are "based on releases in our data": one item per collaborating artist
and type, counting the distinct recordings, releases or relations behind it.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass

from songnexus.core.graph.filters import NodeFilter
from songnexus.core.graph.model import ArtistGraph, Edge, EdgeKind, Evidence


class CollaborationType(enum.StrEnum):
    """A collaborations tab."""

    FEATURE = "FEATURE"  # performed together, in either direction
    PRODUCTION = "PRODUCTION"  # produced for, was produced by, or co-produced
    BAND = "BAND"  # bands, side projects, personas, supporting and teaching
    CREDIT = "CREDIT"  # contributions, samples and engineering, either direction


class ProductionDirection(enum.StrEnum):
    """Who produced whom, from the artist's side (the producer view, R2-2)."""

    PRODUCED_FOR = "PRODUCED_FOR"  # the artist produced the collaborator's music
    PRODUCED_BY = "PRODUCED_BY"  # the collaborator produced the artist's music
    CO_PRODUCED = "CO_PRODUCED"  # they produced something together


TYPE_KINDS: dict[CollaborationType, frozenset[EdgeKind]] = {
    CollaborationType.FEATURE: frozenset({EdgeKind.PERFORMED_WITH}),
    CollaborationType.PRODUCTION: frozenset({EdgeKind.PRODUCED_FOR, EdgeKind.CO_PRODUCED}),
    CollaborationType.BAND: frozenset(
        {EdgeKind.MEMBER_OF, EdgeKind.COLLABORATION, EdgeKind.SUPPORTED, EdgeKind.TAUGHT}
    ),
    CollaborationType.CREDIT: frozenset(
        {EdgeKind.CONTRIBUTED_TO, EdgeKind.SAMPLED, EdgeKind.ENGINEERED}
    ),
}


@dataclass(frozen=True)
class Collaboration:
    """One collaborating artist under one type.

    Attributes:
        artist_id: The collaborator.
        type: The tab it belongs to.
        count: Distinct subjects (recordings, releases, relations) behind it.
        first_year: Earliest known year among those subjects.
        last_year: Latest known year among those subjects.
        evidence: The evidence, in a stable order.
        directions: For production, which ways it went; empty for other types.
    """

    artist_id: str
    type: CollaborationType
    count: int
    first_year: int | None
    last_year: int | None
    evidence: tuple[Evidence, ...]
    directions: frozenset[ProductionDirection] = frozenset()


@dataclass(frozen=True)
class YearRange:
    """Inclusive years; None leaves that end open.

    With a range set, only dated evidence counts: undated relations (most band
    memberships) fall outside every range.
    """

    start: int | None = None
    end: int | None = None

    def contains(self, year: int | None) -> bool:
        """Returns whether a subject year is inside the range."""
        if year is None:
            return False
        return (self.start is None or year >= self.start) and (self.end is None or year <= self.end)


class CollaborationOrder(enum.StrEnum):
    """How collaborators are listed."""

    COUNT = "COUNT"  # most collaborations first
    FIRST_YEAR = "FIRST_YEAR"  # chronological: earliest first, undated last


def _direction(edge: Edge, artist_id: str, evidence: Evidence) -> ProductionDirection:
    if evidence.kind is EdgeKind.CO_PRODUCED:
        return ProductionDirection.CO_PRODUCED
    if edge.role_of(artist_id, evidence) == "producer":
        return ProductionDirection.PRODUCED_FOR
    return ProductionDirection.PRODUCED_BY


def collaborations(
    graph: ArtistGraph,
    artist_id: str,
    collaboration_type: CollaborationType,
    node_filter: NodeFilter | None = None,
    *,
    direction: ProductionDirection | None = None,
    years: YearRange | None = None,
    order: CollaborationOrder = CollaborationOrder.COUNT,
) -> list[Collaboration]:
    """Returns ``artist_id``'s collaborators of one type, most collaborations first.

    Ties are ordered by collaborator name, then ID. Collaborators rejected by
    ``node_filter`` (blocks, genres) are left out. For production, ``direction``
    keeps only collaborations (and their evidence) that went that way. ``years``
    keeps only evidence from subjects dated inside the range.
    """
    kinds = TYPE_KINDS[collaboration_type]
    items = []
    for other_id, edge in graph.neighbors.get(artist_id, {}).items():
        if node_filter is not None and not node_filter.allows(graph.nodes[other_id]):
            continue
        evidence = tuple(
            sorted(
                (e for e in edge.evidence if e.kind in kinds),
                key=lambda e: (e.kind, e.subject_type, e.subject_id),
            )
        )
        if years is not None:
            evidence = tuple(
                e for e in evidence if years.contains(graph.subject_years.get(e.subject_id))
            )
        directions: frozenset[ProductionDirection] = frozenset()
        if collaboration_type is CollaborationType.PRODUCTION:
            if direction is not None:
                evidence = tuple(e for e in evidence if _direction(edge, artist_id, e) is direction)
            directions = frozenset(_direction(edge, artist_id, e) for e in evidence)
        if not evidence:
            continue
        subjects = {e.subject_id for e in evidence}
        dated = [graph.subject_years[s] for s in subjects if s in graph.subject_years]
        items.append(
            Collaboration(
                artist_id=other_id,
                type=collaboration_type,
                count=len(subjects),
                first_year=min(dated, default=None),
                last_year=max(dated, default=None),
                evidence=evidence,
                directions=directions,
            )
        )
    if order is CollaborationOrder.FIRST_YEAR:
        items.sort(
            key=lambda c: (
                c.first_year is None,
                c.first_year or 0,
                graph.nodes[c.artist_id].name,
                c.artist_id,
            )
        )
    else:
        items.sort(key=lambda c: (-c.count, graph.nodes[c.artist_id].name, c.artist_id))
    return items


def collaboration_counts(
    graph: ArtistGraph,
    artist_id: str,
    node_filter: NodeFilter | None = None,
    years: YearRange | None = None,
) -> dict[CollaborationType, int]:
    """Returns the number of collaborators per type (the tab badges)."""
    return {
        t: len(collaborations(graph, artist_id, t, node_filter, years=years))
        for t in CollaborationType
    }


@dataclass(frozen=True)
class Timeline:
    """Collaborative subjects per year and type (the collaborations timeline).

    Attributes:
        years: Year -> type -> distinct subjects (recordings, releases) that year.
        undated: Type -> distinct subjects with no known year.
    """

    years: dict[int, dict[CollaborationType, int]]
    undated: dict[CollaborationType, int]


def collaboration_timeline(
    graph: ArtistGraph, artist_id: str, node_filter: NodeFilter | None = None
) -> Timeline:
    """Counts, per year and type, the distinct subjects behind the artist's collaborations.

    A recording with three collaborators counts once in its year, not three times.
    """
    subjects: dict[CollaborationType, set[str]] = {t: set() for t in CollaborationType}
    for other_id, edge in graph.neighbors.get(artist_id, {}).items():
        if node_filter is not None and not node_filter.allows(graph.nodes[other_id]):
            continue
        for e in edge.evidence:
            for collaboration_type, kinds in TYPE_KINDS.items():
                if e.kind in kinds:
                    subjects[collaboration_type].add(e.subject_id)
    years: dict[int, dict[CollaborationType, int]] = {}
    undated: dict[CollaborationType, int] = {}
    for collaboration_type, ids in subjects.items():
        for subject_id in ids:
            year = graph.subject_years.get(subject_id)
            if year is None:
                undated[collaboration_type] = undated.get(collaboration_type, 0) + 1
            else:
                per_type = years.setdefault(year, {})
                per_type[collaboration_type] = per_type.get(collaboration_type, 0) + 1
    return Timeline(dict(sorted(years.items())), undated)
