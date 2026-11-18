"""Explained recommendations: artists not connected to one artist, each with checkable reasons.

Pure and deterministic. A candidate is recommended only for a reason the viewer
can verify, and only artists with something to play (a performer credit) are
candidates. Reasons:

- ``SHARED_COLLABORATORS``: both artists have credits with the same people. The
  reason names up to ``MAX_VIA`` of them (strongest links first) and the count;
  each step is a connection the client can open.
- ``LISTENERS_IN_COMMON``: one artist is in the other's co-listening list (the
  artists most often played in the same sessions, from aggregate public data).
  Shown only when both audiences meet the k-anonymity floor of
  ``core.listening``, with the rank it rests on.
- ``SAME_LABEL``: both have releases on the same label (the smallest such label).

Directly connected artists (under the default connection kinds) and another
identity of the artist (a person and their stage name) are never recommended.

Ranking is a documented heuristic, not a trained model: the Adamic-Adar score
over shared collaborators (a collaborator who works with few people counts more
than one who works with everybody), plus fixed points for a listening overlap
by strength and for a shared label.
"""

from __future__ import annotations

import enum
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass

from songnexus.core.browse import BrowseIndex, adamic_adar_weight
from songnexus.core.listening import MIN_LISTENERS, Strength, strength_of

MAX_VIA = 3
MAX_RECOMMENDATIONS = 50
LISTENING_POINTS = {Strength.STRONG: 3.0, Strength.MODERATE: 2.0, Strength.WEAK: 1.0}
LABEL_POINTS = 0.5


class ReasonKind(enum.StrEnum):
    """Why an artist is recommended."""

    SHARED_COLLABORATORS = "SHARED_COLLABORATORS"
    LISTENERS_IN_COMMON = "LISTENERS_IN_COMMON"
    SAME_LABEL = "SAME_LABEL"


REASON_MESSAGES = {
    ReasonKind.SHARED_COLLABORATORS: "recommend.sharedCollaborators",  # {count} + via artists
    ReasonKind.LISTENERS_IN_COMMON: "recommend.listenersInCommon",  # {rank} {strength}
    ReasonKind.SAME_LABEL: "recommend.sameLabel",  # {label} + label resource
}


@dataclass(frozen=True)
class Recommendation:
    """One recommended artist and every reason for it.

    Attributes:
        artist_id: The recommended artist.
        score: The ranking score (higher first); see the module docstring.
        shared_count: Collaborators the two share (0 when none).
        via: Up to ``MAX_VIA`` of those collaborators, strongest links first.
        listening_rank: The better rank either artist holds in the other's
            co-listening list, or None.
        listening_strength: The strength that rank maps to, or None.
        label_id: A label both have releases on (the smallest), or None.
    """

    artist_id: str
    score: float
    shared_count: int = 0
    via: tuple[str, ...] = ()
    listening_rank: int | None = None
    listening_strength: Strength | None = None
    label_id: str | None = None

    @property
    def reasons(self) -> tuple[ReasonKind, ...]:
        """The reasons that apply, strongest kind first."""
        found = []
        if self.shared_count:
            found.append(ReasonKind.SHARED_COLLABORATORS)
        if self.listening_rank is not None:
            found.append(ReasonKind.LISTENERS_IN_COMMON)
        if self.label_id is not None:
            found.append(ReasonKind.SAME_LABEL)
        return tuple(found)


def _listening_ranks(index: BrowseIndex, artist_id: str) -> dict[str, int]:
    """Best co-listening rank per other artist, in either direction, above the floor."""
    if index.listeners.get(artist_id, 0) < MIN_LISTENERS:
        return {}
    ranks: dict[str, int] = dict(index.colistening.get(artist_id, {}))
    for other, rank in index.colistened_by.get(artist_id, {}).items():
        ranks[other] = min(rank, ranks.get(other, rank))
    return {o: r for o, r in ranks.items() if index.listeners.get(o, 0) >= MIN_LISTENERS}


def recommend(
    index: BrowseIndex,
    artist_id: str,
    *,
    allowed: Callable[[str], bool] | None = None,
    limit: int = MAX_RECOMMENDATIONS,
) -> list[Recommendation]:
    """Returns artists not connected to ``artist_id``, best first, each with a reason.

    Args:
        index: The browse index.
        artist_id: The artist to recommend from.
        allowed: Which artists may appear, as candidates or as "via" collaborators
            (the viewer's blocks).
        limit: At most this many recommendations.
    """
    graph = index.graph
    adjacency = index.adjacency
    neighbors = adjacency.get(artist_id, {})
    identities = graph.other_identities([artist_id])
    excluded = {artist_id, *neighbors, *identities}

    def candidate(other: str) -> bool:
        return (
            other not in excluded
            and other in index.performers
            and (allowed is None or allowed(other))
        )

    shared: dict[str, list[str]] = defaultdict(list)
    score: dict[str, float] = defaultdict(float)
    for via in neighbors:
        if via in identities or (allowed is not None and not allowed(via)):
            continue
        weight = adamic_adar_weight(index.degree[via])
        for other in adjacency[via]:
            if candidate(other):
                shared[other].append(via)
                score[other] += weight

    listening = {o: r for o, r in _listening_ranks(index, artist_id).items() if candidate(o)}
    for other, rank in listening.items():
        score[other] += LISTENING_POINTS[strength_of(rank)]

    label_of: dict[str, str] = {}
    own_labels = sorted(
        index.artist_labels.get(artist_id, ()),
        key=lambda lb: (len(index.labels[lb].artist_ids), index.labels[lb].name.casefold(), lb),
    )
    for label_id in own_labels:
        for other in sorted(index.labels[label_id].artist_ids):
            if other in graph.nodes and other not in label_of and candidate(other):
                label_of[other] = label_id
                score[other] += LABEL_POINTS

    def via_key(other: str) -> Callable[[str], tuple[float, str, str]]:
        return lambda v: (-min(neighbors[v], adjacency[v][other]), graph.nodes[v].name, v)

    # Ties: the better co-listening rank first, then by name.
    no_rank = MAX_RECOMMENDATIONS * 1000
    ranked = sorted(
        score, key=lambda o: (-score[o], listening.get(o, no_rank), graph.nodes[o].name, o)
    )[:limit]
    results = []
    for other in ranked:
        vias = sorted(shared.get(other, ()), key=via_key(other))
        best_rank = listening.get(other)
        results.append(
            Recommendation(
                artist_id=other,
                score=score[other],
                shared_count=len(vias),
                via=tuple(vias[:MAX_VIA]),
                listening_rank=best_rank,
                listening_strength=None if best_rank is None else strength_of(best_rank),
                label_id=label_of.get(other),
            )
        )
    return results
