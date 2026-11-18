"""Name-based entity resolution: a mention becomes an entity, or a refusal.

The matcher never merges silently. Every call returns one of three decisions:

* ``matched``: one candidate clearly wins, so it is safe to link automatically.
* ``ambiguous``: plausible candidates exist but none clearly wins. A person (or a
  pinned ID in configuration) must decide.
* ``no_match``: nothing is similar enough.

Precision beats recall here: a wrong link corrupts the graph, while a refusal
costs one human decision. Used for seed resolution, imported listening history
and user search input (several real artists are called "Drake").
"""

from __future__ import annotations

import enum
from collections.abc import Sequence
from dataclasses import dataclass, field

from songnexus.core.search import EntityType, SearchIndex
from songnexus.core.text import normalize, string_similarity


class Decision(enum.StrEnum):
    """The outcome of resolving one mention."""

    MATCHED = "matched"
    AMBIGUOUS = "ambiguous"
    NO_MATCH = "no_match"


@dataclass(frozen=True)
class Candidate:
    """An entity that a mention might refer to.

    Attributes:
        entity_id: The candidate's identifier.
        name: Its primary name.
        aliases: Other names it is known by.
        prior: Source-provided relevance or popularity in [0, 1]. Only breaks
            ties between equally good name matches.
        description: Human-readable disambiguation, shown when asking a person.
    """

    entity_id: str
    name: str
    aliases: tuple[str, ...] = ()
    prior: float = 0.0
    description: str = ""


@dataclass(frozen=True)
class ScoredCandidate:
    """A candidate with its scores for one mention."""

    candidate: Candidate
    name_score: float
    matched_name: str
    score: float


@dataclass(frozen=True)
class Resolution:
    """The decision for one mention, with every candidate ranked."""

    mention: str
    decision: Decision
    method: str
    confidence: float
    best: ScoredCandidate | None
    ranked: tuple[ScoredCandidate, ...] = field(default_factory=tuple)

    @property
    def entity_id(self) -> str | None:
        """The matched entity, or None unless the decision is ``matched``."""
        if self.decision is Decision.MATCHED and self.best is not None:
            return self.best.candidate.entity_id
        return None


@dataclass(frozen=True)
class MatchPolicy:
    """Decision thresholds, kept together so they can be tuned on labeled data.

    The defaults favor precision. Changing them requires rerunning the
    resolution evaluation (``data/eval``).

    Attributes:
        accept_threshold: Minimum score to link automatically.
        review_threshold: Below this score the decision is ``no_match``.
        min_margin: Required lead of the best candidate over the runner-up.
        prior_weight: How much a candidate's prior can move its score.
    """

    accept_threshold: float = 0.90
    review_threshold: float = 0.72
    min_margin: float = 0.08
    prior_weight: float = 0.10


DEFAULT_POLICY = MatchPolicy()


def score_candidate(
    normalized_mention: str, candidate: Candidate, policy: MatchPolicy
) -> ScoredCandidate:
    """Scores one candidate by its best-matching name or alias, blended with its prior."""
    best_similarity, best_name = 0.0, candidate.name
    for name in (candidate.name, *candidate.aliases):
        similarity = string_similarity(normalized_mention, normalize(name))
        if similarity > best_similarity:
            best_similarity, best_name = similarity, name
    blended = (1 - policy.prior_weight) * best_similarity + policy.prior_weight * candidate.prior
    return ScoredCandidate(candidate, best_similarity, best_name, blended)


def resolve(
    mention: str,
    candidates: Sequence[Candidate],
    policy: MatchPolicy = DEFAULT_POLICY,
) -> Resolution:
    """Decides which candidate, if any, a mention refers to.

    Args:
        mention: The name as written (a seed, an imported artist name, a query).
        candidates: Entities it might refer to.
        policy: Decision thresholds.

    Returns:
        The decision with every candidate ranked best first (ties broken by ID).
    """
    normalized_mention = normalize(mention)
    if not normalized_mention or not candidates:
        return Resolution(mention, Decision.NO_MATCH, "none", 0.0, None)

    ranked = tuple(
        sorted(
            (score_candidate(normalized_mention, c, policy) for c in candidates),
            key=lambda s: (-s.score, s.candidate.entity_id),
        )
    )
    best = ranked[0]
    runner_up = ranked[1] if len(ranked) > 1 else None
    margin = best.score - runner_up.score if runner_up else 1.0
    method = "exact_name" if best.name_score == 1.0 else "fuzzy_name"
    confidence = round(best.score, 4)

    if best.score < policy.review_threshold:
        return Resolution(mention, Decision.NO_MATCH, method, confidence, best, ranked)

    # Identical normalized names (several artists called "Drake") stay ambiguous
    # unless priors separate them decisively.
    exact_tie = runner_up is not None and runner_up.name_score == 1.0 and best.name_score == 1.0
    required_margin = 2 * policy.min_margin if exact_tie else policy.min_margin
    if best.score >= policy.accept_threshold and margin >= required_margin:
        return Resolution(mention, Decision.MATCHED, method, confidence, best, ranked)
    return Resolution(mention, Decision.AMBIGUOUS, method, confidence, best, ranked)


def decisive_similarity(policy: MatchPolicy) -> float:
    """Returns the lowest name similarity that can affect whether a mention is matched.

    A candidate's score is at most (1 - w)·similarity + w (prior ≤ 1). A match
    needs a score ≥ the accept threshold, and a runner-up can only block it from
    within the margin, so candidates scoring below (accept - margin) never change
    a matched-or-not decision. Lower similarities only decide whether an
    unmatched mention is reported as ambiguous (with weak suggestions) or as no
    match; neither is linked automatically, so precision is unaffected.
    """
    w = policy.prior_weight
    return max(0.0, (policy.accept_threshold - policy.min_margin - w) / (1.0 - w))


def resolve_batch(
    index: SearchIndex,
    mentions: Sequence[str],
    entity_type: EntityType = EntityType.ARTIST,
    policy: MatchPolicy = DEFAULT_POLICY,
) -> list[Resolution]:
    """Resolves many mentions against a search index, one result per mention, in order.

    Candidates are every indexed entity with a name or alias similar enough to
    affect the decision (``SearchIndex.similar_docs``, complete rather than a
    ranked top-k, and fast enough for 2,000 names); the decision comes from
    ``resolve``, so the precision rules apply unchanged. Mentions that
    normalize identically are resolved once.
    """
    floor = decisive_similarity(policy)
    cache: dict[str, Resolution] = {}
    results = []
    for mention in mentions:
        key = normalize(mention)
        if key not in cache:
            docs = index.similar_docs(key, entity_type, floor) if key else []
            candidates = [
                Candidate(
                    entity_id=doc.entity_id,
                    name=doc.name,
                    aliases=tuple(sorted(set(doc.keys.values()) - {doc.name})),
                    prior=doc.prior,
                    description=doc.subtitle,
                )
                for doc in docs
            ]
            cache[key] = resolve(mention, candidates, policy)
        cached = cache[key]
        results.append(cached if cached.mention == mention else _with_mention(cached, mention))
    return results


def _with_mention(resolution: Resolution, mention: str) -> Resolution:
    return Resolution(
        mention,
        resolution.decision,
        resolution.method,
        resolution.confidence,
        resolution.best,
        resolution.ranked,
    )


@dataclass(frozen=True)
class MatchReport:
    """How well automatic matching did on a labeled set.

    Attributes:
        cases: Labeled mentions evaluated.
        matched: Mentions linked automatically.
        correct: Automatic links to the labeled entity.
        positives: Mentions that have a labeled entity.
        precision: correct / matched (1.0 when nothing was matched).
        recall: correct / positives.
        errors: (mention, linked entity, expected entity or None) for each wrong link.
        by_category: (correct, matched, positives) per category.
    """

    cases: int
    matched: int
    correct: int
    positives: int
    precision: float
    recall: float
    errors: tuple[tuple[str, str, str | None], ...]
    by_category: dict[str, tuple[int, int, int]]


def evaluate_matches(
    resolutions: Sequence[Resolution],
    expected: Sequence[str | None],
    categories: Sequence[str],
) -> MatchReport:
    """Scores resolutions against labels (None means "must not be matched")."""
    matched = correct = positives = 0
    errors: list[tuple[str, str, str | None]] = []
    per_category: dict[str, list[int]] = {}
    for resolution, label, category in zip(resolutions, expected, categories, strict=True):
        counts = per_category.setdefault(category, [0, 0, 0])
        if label is not None:
            positives += 1
            counts[2] += 1
        if resolution.entity_id is None:
            continue
        matched += 1
        counts[1] += 1
        if resolution.entity_id == label:
            correct += 1
            counts[0] += 1
        else:
            errors.append((resolution.mention, resolution.entity_id, label))
    return MatchReport(
        cases=len(resolutions),
        matched=matched,
        correct=correct,
        positives=positives,
        precision=correct / matched if matched else 1.0,
        recall=correct / positives if positives else 0.0,
        errors=tuple(errors),
        by_category={k: (v[0], v[1], v[2]) for k, v in sorted(per_category.items())},
    )
