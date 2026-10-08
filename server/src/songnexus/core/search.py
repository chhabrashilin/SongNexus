"""Lexical entity search: exact, prefix, token-prefix and typo-tolerant matching.

For a query q (normalized with the same function as ingestion, so names in any
script are searchable):

1. Candidate generation (cheap, high recall): exact key lookup, key-prefix range
   scan over sorted keys, and a trigram inverted index.
2. Scoring (precise, candidates only), per key, best key wins:

       exact match                1.00
       key starts with q          0.82 to 0.92 (longer remainder scores lower)
       every q token prefixes     0.80
         a key token
       fuzzy (edit or trigram)    0.75 x similarity, if similarity >= 0.5

   Alias matches are multiplied by 0.97, so a primary name beats an alias.
3. Ranking: 0.85 x text score + 0.15 x popularity prior (log-scaled). Equal
   scores rank artists before releases before recordings, then by name and ID,
   so results are stable.
4. Eponymous lift: when a release or recording matches and its title is made of
   its own artist's name tokens (the album "BEYONCÉ" by Beyoncé, "McCartney" by
   Paul McCartney), that artist ranks just above it, and is added if the query
   did not match it directly. Someone typing a name they share with an album
   most likely means the artist.

The weights are a documented starting point, gated on the labeled set
(``data/eval/search_cases.json``, MRR >= 0.95).
"""

from __future__ import annotations

import bisect
import enum
import heapq
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


class EntityType(enum.StrEnum):
    """A searchable entity type, in tie-break order."""

    ARTIST = "artist"
    RELEASE = "release"
    RECORDING = "recording"


_TYPE_ORDER = {t: i for i, t in enumerate(EntityType)}


class MatchType(enum.StrEnum):
    """How a hit matched the query."""

    EXACT = "exact"
    PREFIX = "prefix"
    TOKEN_PREFIX = "token_prefix"  # noqa: S105 - a match type, not a credential
    FUZZY = "fuzzy"
    EPONYMOUS = "eponymous"  # the artist of a matching self-titled release


@dataclass
class SearchDoc:
    """One searchable entity.

    Attributes:
        entity_type: Artist, release or recording.
        entity_id: Its canonical ID.
        name: Display name.
        subtitle: Disambiguating context ("Album · Kendrick Lamar · 2015").
        prior: Popularity prior in [0, 1].
        artist_ids: Primary artists (releases and recordings), for the eponymous lift.
    """

    entity_type: EntityType
    entity_id: str
    name: str
    subtitle: str = ""
    prior: float = 0.0
    artist_ids: tuple[str, ...] = ()
    keys: dict[str, str] = field(default_factory=dict)  # key -> the name it came from
    primary_keys: set[str] = field(default_factory=set)


@dataclass(frozen=True)
class SearchHit:
    """One ranked result."""

    entity_type: EntityType
    entity_id: str
    name: str
    subtitle: str
    score: float
    match_type: MatchType
    matched_on: str
    prior: float = 0.0


class SearchIndex:
    """An in-memory lexical index. Build with ``add``, then ``freeze`` before searching."""

    def __init__(self) -> None:
        self._docs: list[SearchDoc] = []
        self._by_key: dict[str, list[int]] = defaultdict(list)
        self._sorted_keys: list[str] = []
        self._by_trigram: dict[str, set[str]] = defaultdict(set)
        self._key_types: dict[str, frozenset[EntityType]] = {}
        self._keys_by_length: dict[int, list[str]] = defaultdict(list)
        self._artist_index: dict[str, int] = {}
        self._frozen = False

    def add(self, doc: SearchDoc, names: Iterable[str], aliases: Iterable[str] = ()) -> None:
        """Adds a document under its names and aliases.

        Raises:
            RuntimeError: The index is frozen.
        """
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
        if doc.entity_type is EntityType.ARTIST:
            self._artist_index[doc.entity_id] = index
        for key in doc.keys:
            self._by_key[key].append(index)

    def freeze(self) -> SearchIndex:
        """Builds the prefix and trigram structures; the index becomes read-only."""
        self._sorted_keys = sorted(self._by_key)
        for key in self._sorted_keys:
            for gram in trigrams(key):
                self._by_trigram[gram].add(key)
            self._key_types[key] = frozenset(self._docs[i].entity_type for i in self._by_key[key])
            self._keys_by_length[len(key)].append(key)
        self._frozen = True
        return self

    def __len__(self) -> int:
        return len(self._docs)

    def exact(self, name: str, entity_type: EntityType | None = None) -> list[SearchDoc]:
        """Returns documents whose name or alias normalizes exactly to ``name``."""
        docs = [self._docs[i] for i in self._by_key.get(normalize(name), [])]
        return [d for d in docs if entity_type is None or d.entity_type is entity_type]

    def search(
        self,
        query: str,
        *,
        limit: int = 10,
        entity_types: frozenset[EntityType] | None = None,
        exclude: frozenset[str] = frozenset(),
    ) -> list[SearchHit]:
        """Returns the best ``limit`` hits for ``query``.

        Args:
            query: What the user typed.
            limit: Maximum number of hits.
            entity_types: Restrict to these types (all when None).
            exclude: Entity IDs never to return (for example, blocked artists).
        """
        q = normalize(query)
        if not q:
            return []
        best: dict[int, tuple[float, MatchType, str]] = {}
        for key in self._candidate_keys(q, entity_types):
            scored = _key_score(q, key)
            if scored is None:
                continue
            text_score, match_type = scored
            for doc_index in self._by_key[key]:
                doc = self._docs[doc_index]
                if entity_types and doc.entity_type not in entity_types:
                    continue
                if doc.entity_id in exclude:
                    continue
                score = text_score if key in doc.primary_keys else text_score * ALIAS_PENALTY
                if doc_index not in best or score > best[doc_index][0]:
                    best[doc_index] = (score, match_type, doc.keys[key])

        scores = {
            doc_index: (
                TEXT_WEIGHT * text_score + PRIOR_WEIGHT * self._docs[doc_index].prior,
                m,
                on,
            )
            for doc_index, (text_score, m, on) in best.items()
        }
        if entity_types is None or EntityType.ARTIST in entity_types:
            self._lift_eponymous_artists(scores, exclude)
        hits = [
            SearchHit(
                doc.entity_type,
                doc.entity_id,
                doc.name,
                doc.subtitle,
                round(score, 4),
                match_type,
                matched_on,
                doc.prior,
            )
            for doc_index, (score, match_type, matched_on) in scores.items()
            for doc in (self._docs[doc_index],)
        ]
        hits.sort(key=lambda h: (-h.score, _TYPE_ORDER[h.entity_type], h.name, h.entity_id))
        return hits[:limit]

    def _lift_eponymous_artists(
        self, scores: dict[int, tuple[float, MatchType, str]], exclude: frozenset[str]
    ) -> None:
        """Ranks the artist of each matching self-titled work just above that work."""
        lifts: dict[int, tuple[float, MatchType, str]] = {}
        for doc_index, (score, _, _) in scores.items():
            work = self._docs[doc_index]
            title_tokens = set(normalize(work.name).split())
            for artist_id in work.artist_ids:
                artist_index = self._artist_index.get(artist_id)
                if artist_index is None or artist_id in exclude:
                    continue
                artist = self._docs[artist_index]
                if not title_tokens or not any(
                    title_tokens <= set(key.split()) for key in artist.keys
                ):
                    continue
                current = scores.get(artist_index) or lifts.get(artist_index)
                lifted = score + 1e-4
                if current is None:
                    lifts[artist_index] = (lifted, MatchType.EPONYMOUS, work.name)
                elif current[0] < lifted:
                    lifts[artist_index] = (lifted, current[1], current[2])
        scores.update(lifts)

    def similar_docs(
        self, q: str, entity_type: EntityType, min_similarity: float
    ) -> list[SearchDoc]:
        """Returns every document of a type with a key at least ``min_similarity`` similar to ``q``.

        Complete, not ranked: unlike ``search`` there is no candidate cap, so
        batch resolution sees every competitor that could change a decision.
        Two classic filters keep it fast without losing any match:

        - length: names whose lengths differ by more than k are over k edits apart;
        - q-gram count: names within k edits share at least |T(q)| - 4k padded
          trigrams (an edit, or an adjacent transposition, destroys at most 4),
          and trigram similarity ≥ s needs at least s·|T(q)| shared trigrams.

        Here k is the most edits ``min_similarity`` allows for that key's length.
        When the count bound reaches zero (very long names), keys sharing no
        trigram could still qualify, so keys of a close length are also checked.

        Args:
            q: A normalized mention.
            entity_type: The type to return.
            min_similarity: The ``string_similarity`` floor.
        """
        q_grams = trigrams(q)
        longest = math.floor(len(q) / max(min_similarity, 1e-9))
        counts: dict[str, int] = {}
        for gram in q_grams:
            for key in self._by_trigram.get(gram, ()):
                counts[key] = counts.get(key, 0) + 1
        # Key lengths whose count bound is not positive: such keys can qualify
        # while sharing no trigram, so they are checked directly.
        for length in range(1, longest + 1):
            edits = math.floor((1.0 - min_similarity) * max(len(q), length) + 1e-9)
            if abs(length - len(q)) <= edits and len(q_grams) - 4 * edits <= 0:
                for key in self._keys_by_length.get(length, ()):
                    counts.setdefault(key, 0)
        found: dict[int, SearchDoc] = {}
        for key, shared in counts.items():
            if entity_type not in self._key_types[key]:
                continue
            length = max(len(q), len(key))
            max_edits = math.floor((1.0 - min_similarity) * length + 1e-9)
            edit_possible = (
                abs(len(q) - len(key)) <= max_edits and shared >= len(q_grams) - 4 * max_edits
            )
            trigram_possible = shared >= min_similarity * len(q_grams)
            if not (edit_possible or trigram_possible):
                continue
            if string_similarity(q, key, floor=min_similarity) < min_similarity:
                continue
            for doc_index in self._by_key[key]:
                doc = self._docs[doc_index]
                if doc.entity_type is entity_type:
                    found[doc_index] = doc
        return [found[i] for i in sorted(found)]

    def _candidate_keys(self, q: str, entity_types: frozenset[EntityType] | None) -> set[str]:
        """Returns keys worth scoring: exact, prefix, and the best trigram overlaps.

        Keys with no document of the requested types are skipped before ranking,
        so (say) song titles never crowd artists out of the candidate budget.
        """

        def wanted(key: str) -> bool:
            return entity_types is None or not self._key_types[key].isdisjoint(entity_types)

        candidates: set[str] = set()
        for exact in (q, q.replace(" ", "")):
            if exact in self._by_key and wanted(exact):
                candidates.add(exact)
        start = bisect.bisect_left(self._sorted_keys, q)
        for key in self._sorted_keys[start : start + MAX_PREFIX_CANDIDATES]:
            if not key.startswith(q):
                break
            if wanted(key):
                candidates.add(key)
        # Keys sharing trigrams with the query or its longest token, which finds
        # token prefixes ("lamar" -> "kendrick lamar") and typos.
        longest = max(q.split(), key=len)
        gram_counts: Counter[str] = Counter()
        for gram in trigrams(q) | trigrams(longest):
            for key in self._by_trigram.get(gram, ()):
                gram_counts[key] += 1
        # Partial selection, same order as a full sort by (-count, key).
        ranked = heapq.nsmallest(
            MAX_TRIGRAM_CANDIDATES,
            ((key, count) for key, count in gram_counts.items() if wanted(key)),
            key=lambda kv: (-kv[1], kv[0]),
        )
        candidates.update(key for key, _ in ranked)
        return candidates


def _key_score(q: str, key: str) -> tuple[float, MatchType] | None:
    if key == q:
        return 1.0, MatchType.EXACT
    if key.startswith(q):
        return 0.82 + 0.10 * (len(q) / len(key)), MatchType.PREFIX
    key_tokens = key.split()
    if all(any(kt.startswith(qt) for kt in key_tokens) for qt in q.split()):
        return 0.80, MatchType.TOKEN_PREFIX
    similarity = string_similarity(q, key, floor=FUZZY_FLOOR)
    if similarity >= FUZZY_FLOOR:
        return 0.75 * similarity, MatchType.FUZZY
    return None


def log_prior(value: float, max_value: float) -> float:
    """Returns ``value`` log-scaled into [0, 1] against ``max_value``."""
    if max_value <= 0:
        return 0.0
    return math.log1p(value) / math.log1p(max_value)


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EvalCase:
    """A labeled query: what a user typing ``query`` is looking for."""

    query: str
    category: str
    relevant: frozenset[str]


@dataclass(frozen=True)
class EvalReport:
    """Ranking quality on a labeled set.

    Attributes:
        cases: Number of cases evaluated.
        mrr: Mean reciprocal rank of the first relevant hit (0 when missing).
        precision_at_1: Share of cases whose top hit is relevant.
        recall_at_5: Mean share of relevant entities found in the top 5.
        by_category: MRR per case category.
        misses: Queries whose first relevant hit is not ranked first.
    """

    cases: int
    mrr: float
    precision_at_1: float
    recall_at_5: float
    by_category: dict[str, float]
    misses: tuple[str, ...]


def evaluate(index: SearchIndex, cases: Iterable[EvalCase], *, limit: int = 10) -> EvalReport:
    """Evaluates ``index`` on labeled cases."""
    reciprocal_ranks: list[float] = []
    top1: list[float] = []
    recall5: list[float] = []
    per_category: dict[str, list[float]] = defaultdict(list)
    misses: list[str] = []
    for case in cases:
        ranked = [h.entity_id for h in index.search(case.query, limit=limit)]
        rank = next((i for i, e in enumerate(ranked, start=1) if e in case.relevant), None)
        rr = 1.0 / rank if rank else 0.0
        reciprocal_ranks.append(rr)
        per_category[case.category].append(rr)
        top1.append(1.0 if rank == 1 else 0.0)
        recall5.append(len(set(ranked[:5]) & case.relevant) / len(case.relevant))
        if rank != 1:
            misses.append(case.query)

    def mean(values: list[float]) -> float:
        return sum(values) / len(values) if values else 0.0

    return EvalReport(
        cases=len(reciprocal_ranks),
        mrr=mean(reciprocal_ranks),
        precision_at_1=mean(top1),
        recall_at_5=mean(recall5),
        by_category={c: mean(v) for c, v in sorted(per_category.items())},
        misses=tuple(misses),
    )
