"""Listener overlap evaluation against an independent population (offline, research data).

Does ListenBrainz co-listening agree with who listens to what elsewhere? The
Last.fm 360K dataset (Celma, 2010; non-commercial research use, registered as
``EVALUATION`` in the source registry) lists, per user, the artists they played,
with MusicBrainz artist IDs. It is read straight from the downloaded archive and
never stored: only the aggregate result is reported.

For catalog artists, each artist's Last.fm listener set is built, and

* **positives** are pairs ListenBrainz lists as co-listened (B in A's top 100),
* **negatives** are random catalog pairs ListenBrainz does not list,

scored by the Jaccard overlap of their Last.fm listener sets. AUC 0.5 is chance;
higher means the two populations agree on which audiences overlap. The data are
from 2008-2009, so this measures agreement, not current overlap.
"""

from __future__ import annotations

import random
import tarfile
from collections import defaultdict
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path

from songnexus.core.metrics import roc_auc

TSV_MEMBER = "lastfm-dataset-360K/usersha1-artmbid-artname-plays.tsv"


@dataclass(frozen=True)
class ListeningAgreement:
    """The evaluation report."""

    artists_in_both: int
    positive_pairs: int
    negative_pairs: int
    auc: float | None
    median_jaccard_positive: float | None
    median_jaccard_negative: float | None


def lastfm_rows(archive: Path) -> Iterator[tuple[str, str]]:
    """Yields (user hash, artist MBID) from the 360K archive, streaming."""
    with tarfile.open(archive, "r:gz") as tar:
        member = tar.extractfile(TSV_MEMBER)
        if member is None:
            raise FileNotFoundError(f"{TSV_MEMBER} missing from {archive}")
        for raw in member:
            parts = raw.decode("utf-8", "replace").rstrip("\n").split("\t")
            if len(parts) >= 2 and parts[1]:  # noqa: PLR2004 - user, artist columns
                yield parts[0], parts[1]


def listener_sets(rows: Iterable[tuple[str, str]], artists: set[str]) -> dict[str, set[str]]:
    """Returns artist MBID -> user hashes, for the given artists only."""
    sets: dict[str, set[str]] = defaultdict(set)
    for user, artist in rows:
        if artist in artists:
            sets[artist].add(user)
    return dict(sets)


def _jaccard(a: set[str], b: set[str]) -> float:
    union = len(a | b)
    return len(a & b) / union if union else 0.0


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    return ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2


def listening_agreement(
    colistened: Mapping[str, Iterable[str]],
    listeners: Mapping[str, set[str]],
    *,
    negatives_per_positive: int = 1,
    seed: int = 620,
) -> ListeningAgreement:
    """Compares ListenBrainz co-listening with Last.fm listener overlap.

    Args:
        colistened: Artist MBID -> MBIDs ListenBrainz lists as co-listened.
        listeners: Artist MBID -> Last.fm user hashes.
        negatives_per_positive: Random unlisted pairs sampled per listed pair.
        seed: Fixes the negative sample.
    """
    present = sorted(listeners)
    listed = {
        (a, b) for a, bs in colistened.items() for b in bs if a in listeners and b in listeners
    }
    positive = [_jaccard(listeners[a], listeners[b]) for a, b in sorted(listed)]
    rng = random.Random(seed)  # noqa: S311 - a reproducible sample, not security
    negative: list[float] = []
    attempts = 0
    target = len(positive) * negatives_per_positive
    while len(negative) < target and attempts < target * 20 and len(present) > 1:
        attempts += 1
        a, b = rng.sample(present, 2)
        if (a, b) in listed or (b, a) in listed:
            continue
        negative.append(_jaccard(listeners[a], listeners[b]))
    return ListeningAgreement(
        artists_in_both=len(present),
        positive_pairs=len(positive),
        negative_pairs=len(negative),
        auc=roc_auc(positive, negative),
        median_jaccard_positive=_median(positive),
        median_jaccard_negative=_median(negative),
    )
