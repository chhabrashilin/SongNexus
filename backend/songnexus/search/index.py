"""Lexical entity search: exact, prefix, token-prefix, and typo-tolerant fuzzy.

Pipeline for a query q (normalized with the same function as ingestion):

1. **Candidate generation** (cheap, high recall):
   exact key lookup + key-prefix range scan (bisect over sorted keys) +
   trigram inverted index (keys sharing the most trigrams with q).
2. **Scoring** (precise, only on candidates), per key, best key wins:

       exact match               1.00
       key starts with q         0.82 .. 0.92 (longer remainder = lower)
       every q token prefixes    0.80
         a key token
       fuzzy (edit/trigram)      0.75 * similarity, if similarity >= 0.5

   Alias matches are multiplied by 0.97 so a primary name beats an alias.
3. **Ranking**: final = 0.85 * text_score + 0.15 * popularity_prior, where the
   prior is log-scaled graph degree (artists) or credit count (tracks).

The weights are a documented starting point, evaluated with
``songnexus eval-search`` (MRR, Precision@k, Recall@k). Semantic retrieval and
reciprocal-rank fusion are Phase 4 (docs/decisions/ADR-002-search-architecture.md).
"""

from __future__ import annotations

import bisect
import math
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field

from songnexus.core.text import name_keys, normalize, string_similarity, trigrams

TEXT_WEIGHT = 0.85
PRIOR_WEIGHT = 0.15
ALIAS_PENALTY = 0.97
FUZZY_FLOOR = 0.5
MAX_TRIGRAM_CANDIDATES = 400
MAX_PREFIX_CANDIDATES = 400


@dataclass
class SearchDoc:
    entity_type: str  # artist | track | album
    entity_id: str
    name: str
    subtitle: str = ""
    prior: float = 0.0
    # key -> the display string it came from (name or alias)
    keys: dict[str, str] = field(default_factory=dict)
    primary_keys: set[str] = field(default_factory=set)


@dataclass(frozen=True)
class SearchHit:
    entity_type: str
    entity_id: str
    name: str
    subtitle: str
    score: float
    match_type: str
    matched_on: str


class SearchIndex:
    def __init__(self) -> None:
        self._docs: list[SearchDoc] = []
        self._by_key: dict[str, list[int]] = defaultdict(list)
        self._sorted_keys: list[str] = []
        self._by_trigram: dict[str, set[str]] = defaultdict(set)
        self._frozen = False

    def add(self, doc: SearchDoc, names: Iterable[str], aliases: Iterable[str] = ()) -> None:
        if self._frozen:
            raise RuntimeError("index is frozen")
        for name in names:
            for key in name_keys(name):
                doc.keys.setdefault(key, name)
                doc.primary_keys.add(key)
        for alias in aliases:
            for key in name_keys(alias):
                doc.keys.setdefault(key, alias)
        index = len(self._docs)
        self._docs.append(doc)
        for key in doc.keys:
            self._by_key[key].append(index)

    def freeze(self) -> SearchIndex:
        self._sorted_keys = sorted(self._by_key)
        for key in self._sorted_keys:
            for gram in trigrams(key):
                self._by_trigram[gram].add(key)
        self._frozen = True
        return self

    def __len__(self) -> int:
        return len(self._docs)

    def exact(self, name: str, entity_type: str | None = None) -> list[SearchDoc]:
        """Documents whose name or alias normalizes exactly to ``name``."""
        docs = [self._docs[i] for i in self._by_key.get(normalize(name), [])]
        return [d for d in docs if entity_type is None or d.entity_type == entity_type]

    def search(self, query: str, limit: int = 10, entity_types: frozenset[str] | None = None) -> list[SearchHit]:
        q = normalize(query)
        if not q:
            return []
        candidate_keys = self._candidate_keys(q)
        best: dict[int, tuple[float, str, str]] = {}
        for key in candidate_keys:
            text_score, match_type = _key_score(q, key)
            if text_score <= 0:
                continue
            for doc_index in self._by_key[key]:
                doc = self._docs[doc_index]
                if entity_types and doc.entity_type not in entity_types:
                    continue
                score = text_score if key in doc.primary_keys else text_score * ALIAS_PENALTY
                if score > best.get(doc_index, (0.0, "", ""))[0]:
                    best[doc_index] = (score, match_type, doc.keys[key])

        hits = []
        for doc_index, (text_score, match_type, matched_on) in best.items():
            doc = self._docs[doc_index]
            final = TEXT_WEIGHT * text_score + PRIOR_WEIGHT * doc.prior
            hits.append(
                SearchHit(
                    doc.entity_type, doc.entity_id, doc.name, doc.subtitle, round(final, 4), match_type, matched_on
                )
            )
        hits.sort(key=lambda h: (-h.score, h.name, h.entity_id))
        return hits[:limit]

    def _candidate_keys(self, q: str) -> set[str]:
        candidates: set[str] = set()
        if q in self._by_key:
            candidates.add(q)
        compact = q.replace(" ", "")
        if compact in self._by_key:
            candidates.add(compact)
        start = bisect.bisect_left(self._sorted_keys, q)
        for key in self._sorted_keys[start : start + MAX_PREFIX_CANDIDATES]:
            if not key.startswith(q):
                break
            candidates.add(key)
        # Token-prefix candidates: keys containing a token that starts with the
        # query's longest token (e.g. "lamar" -> "kendrick lamar").
        longest = max(q.split(), key=len)
        gram_counts: Counter[str] = Counter()
        for gram in trigrams(q) | trigrams(longest):
            for key in self._by_trigram.get(gram, ()):
                gram_counts[key] += 1
        candidates.update(key for key, _ in gram_counts.most_common(MAX_TRIGRAM_CANDIDATES))
        return candidates


def _key_score(q: str, key: str) -> tuple[float, str]:
    if key == q:
        return 1.0, "exact"
    if key.startswith(q):
        return 0.82 + 0.10 * (len(q) / len(key)), "prefix"
    key_tokens = key.split()
    if all(any(kt.startswith(qt) for kt in key_tokens) for qt in q.split()):
        return 0.80, "token_prefix"
    similarity = string_similarity(q, key)
    if similarity >= FUZZY_FLOOR:
        return 0.75 * similarity, "fuzzy"
    return 0.0, "none"


def log_prior(value: float, max_value: float) -> float:
    if max_value <= 0:
        return 0.0
    return math.log1p(value) / math.log1p(max_value)
