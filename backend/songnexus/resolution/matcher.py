"""Name-based entity resolution: mention -> candidate entity, with a decision.

The matcher never merges silently. Every call returns one of three decisions:

* ``matched``   - a single candidate clearly wins; safe to link automatically.
* ``ambiguous`` - plausible candidates exist but none clearly wins; a human
                  (or a pinned ID in configuration) must decide.
* ``no_match``  - nothing is similar enough.

Used by (1) seed resolution against MusicBrainz search results and
(2) the agent, which must not guess which "Drake" a user meant.
Cross-source matching (Discogs/Wikidata, Phase 1) reuses this module with
candidate generation from our own search index.
"""

from __future__ import annotations

import enum
from collections.abc import Sequence
from dataclasses import dataclass, field

from songnexus.core.text import normalize, string_similarity


class Decision(enum.StrEnum):
    MATCHED = "matched"
    AMBIGUOUS = "ambiguous"
    NO_MATCH = "no_match"


@dataclass(frozen=True)
class Candidate:
    entity_id: str
    name: str
    aliases: tuple[str, ...] = ()
    # Source-provided relevance or popularity, normalized to [0, 1]. Used only
    # as a tie-breaker between equally good name matches.
    prior: float = 0.0
    description: str = ""


@dataclass(frozen=True)
class ScoredCandidate:
    candidate: Candidate
    name_score: float
    matched_name: str
    score: float


@dataclass(frozen=True)
class Resolution:
    mention: str
    decision: Decision
    method: str
    confidence: float
    best: ScoredCandidate | None
    ranked: tuple[ScoredCandidate, ...] = field(default_factory=tuple)

    @property
    def entity_id(self) -> str | None:
        return self.best.candidate.entity_id if self.decision is Decision.MATCHED and self.best else None


@dataclass(frozen=True)
class MatchPolicy:
    """Thresholds, kept in one place so they can be tuned against labeled data.

    Defaults were chosen conservatively (precision over recall) and are
    documented in docs/decisions/ADR-004-entity-resolution.md. They must be
    re-validated against evaluation/entity_resolution_cases.json when changed.
    """

    accept_threshold: float = 0.90  # minimum score to auto-link
    review_threshold: float = 0.72  # below this, report no_match
    min_margin: float = 0.08  # required lead over the runner-up
    prior_weight: float = 0.10  # how much priors can move the final score


DEFAULT_POLICY = MatchPolicy()


def score_candidate(mention_norm: str, candidate: Candidate, policy: MatchPolicy) -> ScoredCandidate:
    best_sim, best_name = 0.0, candidate.name
    for name in (candidate.name, *candidate.aliases):
        sim = string_similarity(mention_norm, normalize(name))
        if sim > best_sim:
            best_sim, best_name = sim, name
    blended = (1 - policy.prior_weight) * best_sim + policy.prior_weight * candidate.prior
    return ScoredCandidate(candidate, best_sim, best_name, blended)


def resolve(
    mention: str,
    candidates: Sequence[Candidate],
    policy: MatchPolicy = DEFAULT_POLICY,
) -> Resolution:
    mention_norm = normalize(mention)
    if not mention_norm or not candidates:
        return Resolution(mention, Decision.NO_MATCH, "none", 0.0, None)

    ranked = tuple(
        sorted(
            (score_candidate(mention_norm, c, policy) for c in candidates),
            key=lambda s: (-s.score, s.candidate.entity_id),
        )
    )
    best = ranked[0]
    runner_up = ranked[1] if len(ranked) > 1 else None
    margin = best.score - runner_up.score if runner_up else 1.0
    method = "exact_name" if best.name_score == 1.0 else "fuzzy_name"

    if best.score < policy.review_threshold:
        return Resolution(mention, Decision.NO_MATCH, method, best.score, best, ranked)

    # Two candidates with identical normalized names (e.g. several artists
    # called "Drake") are ambiguous unless priors separate them decisively.
    exact_tie = runner_up is not None and runner_up.name_score == 1.0 and best.name_score == 1.0
    if (
        best.score >= policy.accept_threshold
        and margin >= policy.min_margin
        and not (exact_tie and margin < 2 * policy.min_margin)
    ):
        return Resolution(mention, Decision.MATCHED, method, round(best.score, 4), best, ranked)
    return Resolution(mention, Decision.AMBIGUOUS, method, round(best.score, 4), best, ranked)
