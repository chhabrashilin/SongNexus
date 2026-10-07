"""An artist's collaborations, grouped the way listeners think about them (US-16).

Counts are "based on releases in our data": one item per collaborating artist
and type, counting the distinct recordings, releases or relations behind it.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass

from songnexus.core.graph.filters import NodeFilter
from songnexus.core.graph.model import ArtistGraph, EdgeKind, Evidence


class CollaborationType(enum.StrEnum):
    """A collaborations tab."""

    FEATURE = "FEATURE"  # performed together, in either direction
    PRODUCTION = "PRODUCTION"  # produced for, was produced by, or co-produced
    BAND = "BAND"  # bands, side projects, personas, supporting and teaching
    CREDIT = "CREDIT"  # contributions, samples and engineering, either direction


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
    """

    artist_id: str
    type: CollaborationType
    count: int
    first_year: int | None
    last_year: int | None
    evidence: tuple[Evidence, ...]


def collaborations(
    graph: ArtistGraph,
    artist_id: str,
    collaboration_type: CollaborationType,
    node_filter: NodeFilter | None = None,
) -> list[Collaboration]:
    """Returns ``artist_id``'s collaborators of one type, most collaborations first.

    Ties are ordered by collaborator name, then ID. Collaborators rejected by
    ``node_filter`` (blocks, genres) are left out.
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
        if not evidence:
            continue
        subjects = {e.subject_id for e in evidence}
        years = [graph.subject_years[s] for s in subjects if s in graph.subject_years]
        items.append(
            Collaboration(
                artist_id=other_id,
                type=collaboration_type,
                count=len(subjects),
                first_year=min(years, default=None),
                last_year=max(years, default=None),
                evidence=evidence,
            )
        )
    items.sort(key=lambda c: (-c.count, graph.nodes[c.artist_id].name, c.artist_id))
    return items


def collaboration_counts(
    graph: ArtistGraph, artist_id: str, node_filter: NodeFilter | None = None
) -> dict[CollaborationType, int]:
    """Returns the number of collaborators per type (the tab badges)."""
    return {t: len(collaborations(graph, artist_id, t, node_filter)) for t in CollaborationType}
