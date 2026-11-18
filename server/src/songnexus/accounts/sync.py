"""From plays to what is stored: per-artist aggregates only (ADR 0006, decision 2).

A play's artist is resolved to a catalog artist by MusicBrainz ID when the
service gives one, otherwise by name with the same conservative matcher as file
import (ambiguous names are not auto-matched). Nothing else about a play is kept:
no track titles, no individual timestamps, no unmatched names (only their count).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

from songnexus.accounts.connectors import Play
from songnexus.core import ids

# Resolves distinct artist names to catalog artist IDs (None when not confidently matched).
NameResolver = Callable[[Sequence[str]], Sequence[str | None]]


@dataclass(frozen=True)
class Tally:
    """Plays of one catalog artist from one sync."""

    plays: int
    last_played_at: int | None


@dataclass(frozen=True)
class Aggregate:
    """A sync's result: per-artist tallies and how many plays could not be matched."""

    tallies: dict[str, Tally]
    unmatched_plays: int


def aggregate(
    plays: Iterable[Play], known_artists: Callable[[str], bool], resolve_names: NameResolver
) -> Aggregate:
    """Tallies plays per catalog artist.

    Args:
        plays: Plays from a connector.
        known_artists: Whether a canonical artist ID is in the catalog.
        resolve_names: The import matcher, applied once to the distinct unresolved names.
    """
    plays = list(plays)
    by_mbid: dict[int, str] = {}
    unresolved: dict[str, list[int]] = {}
    for index, play in enumerate(plays):
        if play.artist_mbid and known_artists(ids.artist_id(play.artist_mbid)):
            by_mbid[index] = ids.artist_id(play.artist_mbid)
        else:
            unresolved.setdefault(play.artist_name, []).append(index)
    names = sorted(unresolved)
    resolved = dict(zip(names, resolve_names(names), strict=True)) if names else {}
    counts: dict[str, int] = {}
    latest: dict[str, int | None] = {}
    unmatched = 0
    for index, play in enumerate(plays):
        artist_id = by_mbid.get(index) or resolved.get(play.artist_name)
        if artist_id is None:
            unmatched += 1
            continue
        counts[artist_id] = counts.get(artist_id, 0) + 1
        if play.played_at is not None:
            latest[artist_id] = max(latest.get(artist_id) or 0, play.played_at)
        else:
            latest.setdefault(artist_id, None)
    return Aggregate(
        {a: Tally(counts[a], latest.get(a)) for a in sorted(counts)},
        unmatched,
    )


def merge(previous: Tally | None, new: Tally) -> Tally:
    """Adds a sync's tally to what is stored."""
    if previous is None:
        return new
    candidates = [t for t in (previous.last_played_at, new.last_played_at) if t is not None]
    return Tally(previous.plays + new.plays, max(candidates) if candidates else None)
