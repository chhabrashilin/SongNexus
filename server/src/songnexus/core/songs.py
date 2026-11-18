"""Song comparison (R2-4, S1): descriptors side by side, an explained similarity, shared credits.

Similarity is a documented weighted mean of four named parts, each in [0, 1].
Each part is shown with its contribution, so the score is never opaque:

* **Mood and sound** (weight 0.40): one minus the mean absolute difference of the
  AcousticBrainz classifier probabilities both songs have (danceable, acoustic,
  aggressive, electronic, happy, party, relaxed, sad, instrumental, bright).
* **Energy** (0.45): loudness and dynamic complexity, one minus the mean difference.
* **Tempo** (0.10): 1 at the same tempo, 0 at a 20 % difference or more; half and
  double time count as the same feel (70 and 140 BPM match).
* **Key** (0.05): distance on the circle of fifths after mapping minor keys to
  their relative major (A minor is C major): 1 for the same, 0 for a tritone.

The weights were fitted, not chosen: on a development half of the catalog's
artists, each part's weight is its separation of same-genre from different-genre
pairs above chance (AUC - 0.5), rounded to 0.05 (``weight_study``, run with
``songnexus eval-songs --fit-weights``). On the held-out half, with the complete
AcousticBrainz snapshot, they score AUC 0.601 against 0.581 for the first,
hand-picked weights (0.40/0.25/0.15/0.20); refitting on the complete data scored
lower (0.590), so these stand. Key carries almost no genre signal but stays
visible at a small weight. See docs/handoff/evaluations.md.

A part counts only when both songs have its inputs; the score is the weighted
mean of the parts present, and ``None`` when no part is.
"""

from __future__ import annotations

import hashlib
import math
import random
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass

from songnexus.core.metrics import roc_auc

MOOD_FIELDS = (
    "danceable",
    "acoustic",
    "aggressive",
    "electronic",
    "happy",
    "party",
    "relaxed",
    "sad",
    "instrumental",
    "bright",
)
WEIGHTS = {"mood": 0.40, "energy": 0.45, "tempo": 0.10, "key": 0.05}
TEMPO_TOLERANCE = 0.20  # relative difference at which tempo similarity reaches 0
DYNAMIC_COMPLEXITY_RANGE = 10.0  # dB; AcousticBrainz values sit in roughly [0, 10]

_PITCH_CLASSES = {
    "C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3, "E": 4, "F": 5, "F#": 6,
    "Gb": 6, "G": 7, "G#": 8, "Ab": 8, "A": 9, "A#": 10, "Bb": 10, "B": 11,
}  # fmt: skip


@dataclass(frozen=True)
class Descriptors:
    """What AcousticBrainz says about one recording; every field may be missing."""

    bpm: float | None = None
    key: str | None = None
    scale: str | None = None  # "major" or "minor"
    key_strength: float | None = None
    length_s: float | None = None
    average_loudness: float | None = None  # [0, 1]
    dynamic_complexity: float | None = None  # dB
    moods: Mapping[str, float] | None = None  # MOOD_FIELDS -> probability

    @classmethod
    def from_fields(cls, fields: Mapping[str, object]) -> Descriptors:
        """Builds descriptors from snapshot fields, ignoring anything malformed."""

        def number(name: str) -> float | None:
            value = fields.get(name)
            return float(value) if isinstance(value, int | float) and math.isfinite(value) else None

        def text(name: str) -> str | None:
            value = fields.get(name)
            return value if isinstance(value, str) and value else None

        moods = {m: v for m in MOOD_FIELDS if (v := number(m)) is not None}
        return cls(
            bpm=number("bpm"),
            key=text("key"),
            scale=text("scale"),
            key_strength=number("key_strength"),
            length_s=number("length_s"),
            average_loudness=number("average_loudness"),
            dynamic_complexity=number("dynamic_complexity"),
            moods=moods or None,
        )


@dataclass(frozen=True)
class Part:
    """One named part of the similarity.

    Attributes:
        name: ``mood``, ``tempo``, ``key`` or ``energy``.
        similarity: In [0, 1].
        weight: Its weight among the parts present (they sum to 1).
        contribution: ``similarity * weight``: what it adds to the score.
    """

    name: str
    similarity: float
    weight: float
    contribution: float


@dataclass(frozen=True)
class Similarity:
    """The score and how it was made."""

    score: float | None
    parts: tuple[Part, ...]


def tempo_similarity(a: float, b: float) -> float:
    """1 at equal tempo (or half/double time), falling to 0 at a 20 % difference."""
    if a <= 0 or b <= 0:
        return 0.0
    ratio = max(a, b) / min(a, b)
    # Half/double time: compare against the nearest power-of-two multiple.
    ratio /= 2.0 ** round(math.log2(ratio))
    difference = abs(ratio - 1) if ratio >= 1 else abs(1 / ratio - 1)
    return max(0.0, 1 - difference / TEMPO_TOLERANCE)


def fifths_position(key: str, scale: str) -> int | None:
    """Position on the circle of fifths (0-11), minor keys at their relative major."""
    pitch = _PITCH_CLASSES.get(key)
    if pitch is None or scale not in {"major", "minor"}:
        return None
    major = (pitch + 3) % 12 if scale == "minor" else pitch
    return (major * 7) % 12  # each fifth is 7 semitones


def key_similarity(a: Descriptors, b: Descriptors) -> float | None:
    """1 for the same key (or its relative), 0 for keys a tritone apart."""
    if not (a.key and a.scale and b.key and b.scale):
        return None
    pa, pb = fifths_position(a.key, a.scale), fifths_position(b.key, b.scale)
    if pa is None or pb is None:
        return None
    steps = abs(pa - pb) % 12
    return 1 - min(steps, 12 - steps) / 6


def _mean_difference(pairs: Iterable[tuple[float, float]]) -> float | None:
    diffs = [abs(x - y) for x, y in pairs]
    return sum(diffs) / len(diffs) if diffs else None


def similarity(
    a: Descriptors, b: Descriptors, weights: Mapping[str, float] = WEIGHTS
) -> Similarity:
    """Returns the explained similarity of two recordings (``weights`` for studies only)."""
    raw: dict[str, float] = {}
    if a.moods and b.moods:
        shared = [(a.moods[m], b.moods[m]) for m in MOOD_FIELDS if m in a.moods and m in b.moods]
        diff = _mean_difference(shared)
        if diff is not None:
            raw["mood"] = 1 - diff
    if a.bpm is not None and b.bpm is not None:
        raw["tempo"] = tempo_similarity(a.bpm, b.bpm)
    key = key_similarity(a, b)
    if key is not None:
        raw["key"] = key
    energy_pairs = []
    if a.average_loudness is not None and b.average_loudness is not None:
        energy_pairs.append((a.average_loudness, b.average_loudness))
    if a.dynamic_complexity is not None and b.dynamic_complexity is not None:
        energy_pairs.append(
            (
                min(a.dynamic_complexity / DYNAMIC_COMPLEXITY_RANGE, 1.0),
                min(b.dynamic_complexity / DYNAMIC_COMPLEXITY_RANGE, 1.0),
            )
        )
    energy = _mean_difference(energy_pairs)
    if energy is not None:
        raw["energy"] = 1 - energy
    raw = {name: value for name, value in raw.items() if weights.get(name, 0) > 0}
    if not raw:
        return Similarity(None, ())
    total = sum(weights[name] for name in raw)
    parts = tuple(
        Part(name, value, weights[name] / total, value * weights[name] / total)
        for name, value in sorted(raw.items(), key=lambda kv: -weights[kv[0]])
    )
    return Similarity(sum(p.contribution for p in parts), parts)


@dataclass(frozen=True)
class SharedCredits:
    """Credits compared by role: who is on both songs, and who on only one."""

    role: str
    both: tuple[str, ...]
    only_a: tuple[str, ...]
    only_b: tuple[str, ...]


def shared_credits(
    credits_a: Iterable[tuple[str, str]], credits_b: Iterable[tuple[str, str]]
) -> list[SharedCredits]:
    """Groups (artist ID, role) credits of two songs by role.

    Roles where both songs share someone come first, then by role name.
    """
    by_role_a: dict[str, set[str]] = {}
    by_role_b: dict[str, set[str]] = {}
    for artist, role in credits_a:
        by_role_a.setdefault(role, set()).add(artist)
    for artist, role in credits_b:
        by_role_b.setdefault(role, set()).add(artist)
    rows = [
        SharedCredits(
            role,
            tuple(sorted(by_role_a.get(role, set()) & by_role_b.get(role, set()))),
            tuple(sorted(by_role_a.get(role, set()) - by_role_b.get(role, set()))),
            tuple(sorted(by_role_b.get(role, set()) - by_role_a.get(role, set()))),
        )
        for role in set(by_role_a) | set(by_role_b)
    ]
    rows.sort(key=lambda r: (not r.both, r.role))
    return rows


@dataclass(frozen=True)
class GenreSeparation:
    """How well similarity separates same-genre pairs from different-genre pairs.

    Attributes:
        recordings: Recordings with descriptors and a primary artist with genres.
        same_genre_pairs: Pairs whose artists share their top genre.
        other_pairs: Pairs whose artists share no genre at all.
        auc: Probability a same-genre pair scores above an other pair (0.5 is chance).
    """

    recordings: int
    same_genre_pairs: int
    other_pairs: int
    auc: float | None


Recordings = Mapping[str, tuple[Descriptors, str, frozenset[str], str]]


def _labelled_pairs(
    recordings: Recordings, pairs: int, seed: int
) -> Iterator[tuple[bool, Descriptors, Descriptors]]:
    """Samples pairs by different artists: True for a shared top genre, False for no shared genre.

    Pairs sharing some genre but not the top one are ambiguous and left out.
    """
    ids_ = sorted(recordings)
    rng = random.Random(seed)  # noqa: S311 - a reproducible sample, not security
    for _ in range(pairs if len(ids_) > 1 else 0):
        a, b = rng.sample(ids_, 2)
        (da, artist_a, genres_a, top_a) = recordings[a]
        (db, artist_b, genres_b, top_b) = recordings[b]
        if artist_a == artist_b:
            continue
        if top_a == top_b:
            yield True, da, db
        elif not genres_a & genres_b:
            yield False, da, db


def _auc(
    pairs: Iterable[tuple[bool, Descriptors, Descriptors]], weights: Mapping[str, float]
) -> tuple[float | None, int, int]:
    positive: list[float] = []
    negative: list[float] = []
    for same, a, b in pairs:
        score = similarity(a, b, weights).score
        if score is not None:
            (positive if same else negative).append(score)
    return roc_auc(positive, negative), len(positive), len(negative)


def genre_separation(
    recordings: Recordings,
    *,
    pairs: int = 4000,
    seed: int = 620,
) -> GenreSeparation:
    """Samples pairs of recordings by different artists and measures the AUC.

    Args:
        recordings: Recording ID -> (descriptors, primary artist ID, artist genre IDs,
            top genre ID).
        pairs: How many pairs to sample.
        seed: Fixes the sample, so the number is reproducible.
    """
    auc, positive, negative = _auc(_labelled_pairs(recordings, pairs, seed), WEIGHTS)
    return GenreSeparation(len(recordings), positive, negative, auc)


@dataclass(frozen=True)
class WeightStudy:
    """How ``WEIGHTS`` were fitted, reproducibly.

    Attributes:
        part_auc: Each part's AUC on the development half.
        fitted: Weights proportional to (AUC - 0.5), rounded to 0.05.
        held_out_current: AUC of ``WEIGHTS`` on the held-out half.
        held_out_fitted: AUC of ``fitted`` on the held-out half.
    """

    part_auc: dict[str, float]
    fitted: dict[str, float]
    held_out_current: float | None
    held_out_fitted: float | None


def weight_study(recordings: Recordings, *, pairs: int = 20000, seed: int = 620) -> WeightStudy:
    """Fits weights on half of the artists and measures them on the other half.

    Artists are split by a hash of their ID, so a song never informs the weights
    used to judge songs by the same artist.
    """

    def half(artist_id: str) -> int:
        return int(hashlib.sha256(artist_id.encode()).hexdigest(), 16) % 2

    dev = {r: v for r, v in recordings.items() if half(v[1]) == 0}
    test = {r: v for r, v in recordings.items() if half(v[1]) == 1}
    part_auc: dict[str, float] = {}
    dev_pairs = list(_labelled_pairs(dev, pairs, seed))
    for name in WEIGHTS:
        auc, _, _ = _auc(dev_pairs, {name: 1.0})
        if auc is not None:
            part_auc[name] = round(auc, 4)
    signal = {name: max(0.0, auc - 0.5) for name, auc in part_auc.items()}
    total = sum(signal.values()) or 1.0
    fitted = {name: round(round(value / total / 0.05) * 0.05, 2) for name, value in signal.items()}
    test_pairs = list(_labelled_pairs(test, pairs, seed))
    return WeightStudy(
        part_auc,
        fitted,
        _auc(test_pairs, WEIGHTS)[0],
        _auc(test_pairs, fitted)[0],
    )
