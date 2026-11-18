"""Evaluation metrics shared by the offline evaluations."""

from __future__ import annotations

import bisect
from collections.abc import Iterable


def roc_auc(positives: Iterable[float], negatives: Iterable[float]) -> float | None:
    """The probability a random positive scores above a random negative (ties count half).

    Computed by binary search over the sorted negatives (Mann-Whitney), so large
    samples stay fast.
    """
    pos, neg = list(positives), sorted(negatives)
    if not pos or not neg:
        return None
    wins = 0.0
    for p in pos:
        below = bisect.bisect_left(neg, p)
        equal = bisect.bisect_right(neg, p) - below
        wins += below + equal / 2
    return wins / (len(pos) * len(neg))
