"""Conversions from core and storage objects to API schemas."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from songnexus.core.graph import collaborations as collab
from songnexus.core.graph.explain import Explanation
from songnexus.core.graph.model import ArtistGraph, Category, EdgeKind, SubjectType
from songnexus.service import schemas as api
from songnexus.storage.catalog_repository import SourceRef

_SUBJECT_COLLECTIONS = {
    SubjectType.RECORDING: "recordings",
    SubjectType.RELEASE: "releases",
    SubjectType.RELATION: "relations",
    SubjectType.LABEL: "labels",
}


def artist_summary(graph: ArtistGraph, artist_id: str) -> api.ArtistSummary:
    """Returns the list form of an artist."""
    node = graph.nodes[artist_id]
    return api.ArtistSummary(
        name=f"artists/{node.id}",
        display_name=node.name,
        disambiguation=node.disambiguation,
        artist_type=node.artist_type,
        country=node.country,
        genre_known=bool(node.genres),
        image_url=image_url(graph, artist_id),
        listeners=graph.listeners.get(artist_id),
    )


def image_url(graph: ArtistGraph, artist_id: str) -> str | None:
    """Returns the ~330 px photo URL of an artist, or None (no photo, or not an artist)."""
    image = graph.images.get(artist_id)
    return image.thumbnail_url if image else None


def artist_image(graph: ArtistGraph, artist_id: str) -> api.ArtistImage | None:
    """Returns an artist's photo with its attribution, or None."""
    image = graph.images.get(artist_id)
    if image is None:
        return None
    return api.ArtistImage(
        url=image.url,
        thumbnail_url=image.thumbnail_url,
        width=image.width,
        height=image.height,
        page_url=image.page_url,
        author=image.author,
        license=image.license,
        license_url=image.license_url,
    )


def kind(edge_kind: EdgeKind) -> api.ConnectionKind:
    """Returns the API enum for an edge kind."""
    return api.ConnectionKind(edge_kind.value.upper())


def kinds_list(kinds: Iterable[EdgeKind]) -> list[api.ConnectionKind]:
    """Returns API kinds in a stable order."""
    order = list(EdgeKind)
    return [kind(k) for k in sorted(set(kinds), key=order.index)]


def category(value: api.ConnectionCategory) -> Category:
    """Returns the core category for an API category."""
    return Category(value.value.lower())


def collaboration_type(value: api.CollaborationType) -> collab.CollaborationType:
    """Returns the core collaboration type for an API one."""
    return collab.CollaborationType(value.value)


def source_links(refs: Iterable[SourceRef]) -> list[api.SourceLink]:
    """Returns API source links."""
    return [api.SourceLink(source=r.source, source_id=r.source_id, url=r.url) for r in refs]


def evidence(
    explanation: Explanation, sources: Mapping[str, list[SourceRef]] | None = None
) -> api.Evidence:
    """Returns an API evidence line, with sources when supplied."""
    collection = _SUBJECT_COLLECTIONS[explanation.subject_type]
    return api.Evidence(
        message_id=explanation.message_id.value,
        kind=kind(explanation.kind),
        from_artist=f"artists/{explanation.from_artist}",
        to_artist=f"artists/{explanation.to_artist}",
        from_role=explanation.from_role,
        to_role=explanation.to_role,
        subject=api.Subject(
            name=f"{collection}/{explanation.subject_id}",
            display_name=explanation.subject_title,
        ),
        sources=source_links((sources or {}).get(explanation.subject_id, [])),
    )


def subject_keys(explanations: Iterable[Explanation]) -> list[tuple[str, str]]:
    """Returns (subject type, subject ID) pairs for a source lookup."""
    return sorted({(e.subject_type.value, e.subject_id) for e in explanations})
