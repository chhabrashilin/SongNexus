"""Collaborations recall: does every collaboration in the raw MusicBrainz data reach the page?

An independent re-derivation, deliberately not reusing the pipeline's parsers or
projection: collaborators are read straight from the raw JSON with the product's
own definitions (US-16), then compared with what ``collaborations`` returns.

* **Feature**: artists credited together on a recording's artist credit.
* **Production**: an artist with a ``producer`` relation on a recording, paired
  with each artist credited on it (either direction).
* **Band**: a ``member of band`` relation between two artists.

Recall per type is |found by both| / |found in raw data|, pooled over the artists
evaluated. Self-pairs and artists missing from the graph (blocked by nothing; the
catalog keeps everyone it references) are excluded.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from songnexus.catalog.snapshot import RawRecord
from songnexus.core import ids
from songnexus.core.graph.collaborations import CollaborationType, collaborations
from songnexus.core.graph.model import ArtistGraph

EVALUATED_TYPES = (CollaborationType.FEATURE, CollaborationType.PRODUCTION, CollaborationType.BAND)
Pairs = dict[CollaborationType, dict[str, set[str]]]
MISSING_EXAMPLES = 5


@dataclass(frozen=True)
class TypeRecall:
    """Recall for one collaboration type."""

    expected: int
    found: int
    recall: float | None
    missing_examples: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class CollaborationRecall:
    """The evaluation report."""

    artists: int
    by_type: dict[str, TypeRecall] = field(default_factory=dict)
    overall: float | None = None


def _credited(credit: list[dict[str, Any]]) -> list[str]:
    return [c["artist"]["id"] for c in credit if isinstance(c.get("artist"), dict)]


def _add(pairs: Pairs, kind: CollaborationType, a: str, b: str) -> None:
    if a != b:
        pairs[kind][a].add(b)
        pairs[kind][b].add(a)


def raw_collaborators(records: Iterable[RawRecord]) -> Pairs:
    """Returns type -> MusicBrainz artist ID -> collaborator IDs, from raw responses."""
    pairs: Pairs = {t: defaultdict(set) for t in EVALUATED_TYPES}
    for record in records:
        body = record.body
        if record.kind == "release":
            for medium in body.get("media", []):
                for track in medium.get("tracks", []):
                    recording = track.get("recording", {})
                    credited = _credited(recording.get("artist-credit", []))
                    for i, a in enumerate(credited):
                        for b in credited[i + 1 :]:
                            _add(pairs, CollaborationType.FEATURE, a, b)
                    for relation in recording.get("relations", []):
                        artist = relation.get("artist")
                        if relation.get("type") == "producer" and isinstance(artist, dict):
                            for performer in credited:
                                _add(pairs, CollaborationType.PRODUCTION, artist["id"], performer)
        elif record.kind == "artist":
            for relation in body.get("relations", []):
                other = relation.get("artist")
                if relation.get("type") == "member of band" and isinstance(other, dict):
                    _add(pairs, CollaborationType.BAND, body["id"], other["id"])
    return pairs


def collaboration_recall(
    graph: ArtistGraph, records: Iterable[RawRecord], musicbrainz_ids: Iterable[str]
) -> CollaborationRecall:
    """Measures recall of ``collaborations`` against the raw data for the given artists."""
    expected_pairs = raw_collaborators(records)
    evaluated = [m for m in musicbrainz_ids if ids.artist_id(m) in graph.nodes]
    by_type: dict[str, TypeRecall] = {}
    total_expected = total_found = 0
    for kind in EVALUATED_TYPES:
        expected = found = 0
        missing: list[tuple[str, str]] = []
        for mbid in evaluated:
            artist_id = ids.artist_id(mbid)
            shown = {c.artist_id for c in collaborations(graph, artist_id, kind)}
            for other in sorted(expected_pairs[kind].get(mbid, set())):
                other_id = ids.artist_id(other)
                if other_id not in graph.nodes:
                    continue
                expected += 1
                if other_id in shown:
                    found += 1
                elif len(missing) < MISSING_EXAMPLES:
                    missing.append((graph.nodes[artist_id].name, graph.nodes[other_id].name))
        by_type[kind.value] = TypeRecall(
            expected, found, found / expected if expected else None, tuple(missing)
        )
        total_expected += expected
        total_found += found
    return CollaborationRecall(
        artists=len(evaluated),
        by_type=by_type,
        overall=total_found / total_expected if total_expected else None,
    )
