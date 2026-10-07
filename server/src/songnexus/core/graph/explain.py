"""Human-readable reasons for connections, as message IDs with parameters.

The server never formats prose. It returns a stable message ID and the facts to
fill in, and the client renders them in the viewer's language. Every message
names its subject (a recording, release, relation or label) so the viewer can
check the evidence at its source.
"""

from __future__ import annotations

import enum
import itertools
from dataclasses import dataclass

from songnexus.core.graph.model import ArtistGraph, Edge, EdgeKind, Evidence, SubjectType


class MessageId(enum.StrEnum):
    """Stable identifiers of explanation messages (keys in the client's catalog)."""

    PERFORMED_TOGETHER = "evidence.performedTogether"  # both primary
    FEATURED = "evidence.featured"  # {to} featured on {from}'s {subject}, or reverse
    PRODUCED = "evidence.produced"  # {producer} produced {performer}'s {subject}
    CO_PRODUCED = "evidence.coProduced"
    CONTRIBUTED = "evidence.contributed"  # {contributor} ({role}) on {performer}'s {subject}
    SAMPLED = "evidence.sampled"  # {performer}'s {subject} samples {sampled}
    ENGINEERED = "evidence.engineered"
    RELATION = "evidence.relation"  # {from} is {fromRole} of/with {to}
    LABEL_MATES = "evidence.labelMates"


@dataclass(frozen=True)
class Explanation:
    """One reason two artists are connected, oriented from ``from_artist``.

    Attributes:
        message_id: Which message the client renders.
        kind: The edge kind.
        from_artist: The artist the explanation starts from.
        to_artist: The other artist.
        from_role: ``from_artist``'s role ("producer", "featured", "member", ...).
        to_role: ``to_artist``'s role.
        subject_type: What the evidence is about.
        subject_id: Its canonical ID.
        subject_title: Its title or name, when known.
    """

    message_id: MessageId
    kind: EdgeKind
    from_artist: str
    to_artist: str
    from_role: str
    to_role: str
    subject_type: SubjectType
    subject_id: str
    subject_title: str | None


_MESSAGE_BY_KIND = {
    EdgeKind.PRODUCED_FOR: MessageId.PRODUCED,
    EdgeKind.CO_PRODUCED: MessageId.CO_PRODUCED,
    EdgeKind.CONTRIBUTED_TO: MessageId.CONTRIBUTED,
    EdgeKind.SAMPLED: MessageId.SAMPLED,
    EdgeKind.ENGINEERED: MessageId.ENGINEERED,
    EdgeKind.MEMBER_OF: MessageId.RELATION,
    EdgeKind.COLLABORATION: MessageId.RELATION,
    EdgeKind.SUPPORTED: MessageId.RELATION,
    EdgeKind.TAUGHT: MessageId.RELATION,
    EdgeKind.LABEL_MATES: MessageId.LABEL_MATES,
}


def _message(evidence: Evidence, from_role: str, to_role: str) -> MessageId:
    if evidence.kind is EdgeKind.PERFORMED_WITH:
        both_primary = from_role == to_role == "primary"
        return MessageId.PERFORMED_TOGETHER if both_primary else MessageId.FEATURED
    return _MESSAGE_BY_KIND[evidence.kind]


# Evidence order within an explanation list: the strongest kinds first.
_KIND_ORDER = {kind: i for i, kind in enumerate(EdgeKind)}


def explain_edge(
    graph: ArtistGraph,
    edge: Edge,
    from_artist: str,
    kinds: frozenset[EdgeKind],
    *,
    limit: int | None = None,
) -> list[Explanation]:
    """Returns the explanations for one edge, oriented from ``from_artist``.

    Ordered by kind (performance first), then subject title, then subject ID, so
    the same edge is always explained the same way.
    """
    to_artist = edge.other(from_artist)
    explanations = []
    for evidence in edge.evidence:
        if evidence.kind not in kinds:
            continue
        from_role, to_role = edge.role_of(from_artist, evidence), edge.role_of(to_artist, evidence)
        explanations.append(
            Explanation(
                message_id=_message(evidence, from_role, to_role),
                kind=evidence.kind,
                from_artist=from_artist,
                to_artist=to_artist,
                from_role=from_role,
                to_role=to_role,
                subject_type=evidence.subject_type,
                subject_id=evidence.subject_id,
                subject_title=graph.subject_titles.get(evidence.subject_id),
            )
        )
    explanations.sort(key=lambda e: (_KIND_ORDER[e.kind], e.subject_title or "", e.subject_id))
    return explanations[:limit] if limit is not None else explanations


def explain_path(
    graph: ArtistGraph,
    path: tuple[str, ...],
    kinds: frozenset[EdgeKind],
    *,
    per_step: int = 3,
) -> list[list[Explanation]]:
    """Returns up to ``per_step`` explanations for each consecutive step of ``path``.

    Raises:
        ValueError: Two consecutive artists are not connected under ``kinds``.
    """
    steps = []
    for u, v in itertools.pairwise(path):
        edge = graph.edge(u, v)
        explanations = explain_edge(graph, edge, u, kinds, limit=per_step) if edge else []
        if not explanations:
            raise ValueError(f"no evidence connects {u} and {v}")
        steps.append(explanations)
    return steps
