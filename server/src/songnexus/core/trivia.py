"""Credit check: a five-question daily trivia game built from published credits.

Pure and deterministic. The same catalog and date always give the same questions,
so everyone plays the same quiz and nothing is stored.

Questions (each is generated from credits in the graph, never invented):

- ``WHO_PRODUCED``: "Who produced <song> by <artist>?"
- ``WHO_FEATURED``: "Which artist is featured on <song> by <artist>?"
- ``WORKED_WITH``: "Which of these artists has worked with <artist>?"
- ``WHICH_LABEL``: "Which label released <release>?" (needs label data)

Fairness:

- Songs and artists are well known: they are drawn from the artists with the
  most connections, using weighted degree as the popularity signal.
- Distractors are plausible: the closest artists (shared genres, a similar era,
  similar prominence) that are demonstrably not correct. For a song, a
  distractor has no credit of any kind on it. For "worked with", a distractor is
  at least three connections away from the artist in the full graph (every kind,
  label mates included), so a real but unrecorded collaboration is unlikely.
- A question is dropped, never guessed, when it cannot get three distractors.
"""

from __future__ import annotations

import enum
import hashlib
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date

from songnexus.core.graph.algorithms import bfs_distances, weighted_degree
from songnexus.core.graph.explain import Explanation, explain_edge
from songnexus.core.graph.model import (
    DEFAULT_CATEGORIES,
    ArtistGraph,
    EdgeKind,
    SubjectType,
    kinds_for,
)

LAUNCH_DAY = date(2026, 10, 7)  # Credit check #1, the same day as the daily puzzle
QUESTIONS_PER_DAY = 5
OPTIONS_PER_QUESTION = 4
SEED = "songnexus-credit-check-v1"

# How many of the best-known artists can be asked about, and how many of the
# best-known artists of a role can show up as options.
POPULAR_ARTISTS = 400
DISTRACTOR_POOL = 400
# The distractors are drawn at random from this many closest matches.
PLAUSIBLE = 10
# Candidates examined per question before giving up on a kind.
ATTEMPTS = 30
MAX_TITLE_LENGTH = 70
MIN_NEIGHBORS = 6
NEARBY_DEPTH = 2
MAX_CREDITED = 2  # producers on a song, or artists on a release, for a clean question

DEFAULT_KINDS = kinds_for(DEFAULT_CATEGORIES)
ALL_KINDS = frozenset(EdgeKind)


class QuestionKind(enum.StrEnum):
    """What a question asks."""

    WHO_PRODUCED = "who_produced"
    WHO_FEATURED = "who_featured"
    WORKED_WITH = "worked_with"
    WHICH_LABEL = "which_label"


KIND_ORDER = tuple(QuestionKind)


@dataclass(frozen=True)
class Question:
    """One question. ``options`` are artist IDs, or label IDs for WHICH_LABEL.

    Attributes:
        id: ``q1`` to ``q5``, stable within a day.
        kind: What is asked.
        options: The shuffled options, exactly one of them correct.
        answer: The correct option.
        subject_id: The recording or release asked about ("" for WORKED_WITH).
        subject_title: Its title ("" for WORKED_WITH).
        artist_id: The artist the question is about: the song's main artist, or
            the artist in "worked with".
    """

    id: str
    kind: QuestionKind
    options: tuple[str, ...]
    answer: str
    subject_id: str
    subject_title: str
    artist_id: str


@dataclass(frozen=True)
class Quiz:
    """One day's credit check."""

    day: date
    number: int
    questions: tuple[Question, ...]

    def question(self, question_id: str) -> Question | None:
        """Returns a question by ID."""
        return next((q for q in self.questions if q.id == question_id), None)


@dataclass(frozen=True)
class LabelFacts:
    """Release-label facts for WHICH_LABEL (the graph does not carry them).

    Attributes:
        release_labels: Release ID to the labels it came out on.
        release_artists: Release ID to its primary artists.
        label_artists: Label ID to the primary artists of its releases.
    """

    release_labels: Mapping[str, frozenset[str]] = field(default_factory=dict)
    release_artists: Mapping[str, frozenset[str]] = field(default_factory=dict)
    label_artists: Mapping[str, frozenset[str]] = field(default_factory=dict)


def stable_int(text: str) -> int:
    """Returns a platform-independent integer for seeding."""
    return int(hashlib.sha256(text.encode()).hexdigest()[:16], 16)


def number_for(day: date) -> int:
    """Returns the quiz number: 1 on the launch day."""
    return (day - LAUNCH_DAY).days + 1


def _year(begin_date: str | None) -> int | None:
    return int(begin_date[:4]) if begin_date and begin_date[:4].isdigit() else None


@dataclass(frozen=True)
class TriviaIndex:
    """Facts derived once per catalog: popularity and who is credited on each song.

    Attributes:
        rank: Artist to popularity rank (0 is best), for artists with detail.
        ranked: Those artists, best known first.
        credited: Subject ID to every artist credited on it in any role.
        producers: Recording ID to its producers.
        primary: Recording ID to its primary artists.
        featured: Recording ID to its featured artists.
        song_pool: Recordings with a clean produced or featured question, best known first.
    """

    graph: ArtistGraph
    rank: Mapping[str, int]
    ranked: tuple[str, ...]
    credited: Mapping[str, frozenset[str]]
    producers: Mapping[str, frozenset[str]]
    primary: Mapping[str, frozenset[str]]
    featured: Mapping[str, frozenset[str]]
    produced_pool: tuple[str, ...]
    featured_pool: tuple[str, ...]
    worked_pool: tuple[str, ...]
    producer_artists: tuple[str, ...]
    performer_artists: tuple[str, ...]


def build_index(graph: ArtistGraph) -> TriviaIndex:
    """Derives the trivia index from the graph."""
    degree = weighted_degree(graph.adjacency(DEFAULT_KINDS))
    nodes = graph.nodes
    ranked = tuple(
        sorted(
            (a for a, n in nodes.items() if n.detail_level != "stub"), key=lambda a: (-degree[a], a)
        )
    )
    rank = {a: i for i, a in enumerate(ranked)}

    credited: dict[str, set[str]] = {}
    producers: dict[str, set[str]] = {}
    primary: dict[str, set[str]] = {}
    featured: dict[str, set[str]] = {}
    for edge in graph.edges.values():
        for ev in edge.evidence:
            if ev.subject_type is not SubjectType.RECORDING:
                continue
            credited.setdefault(ev.subject_id, set()).update((edge.a, edge.b))
            for artist, role in ((edge.a, ev.a_role), (edge.b, ev.b_role)):
                if role == "producer":
                    producers.setdefault(ev.subject_id, set()).add(artist)
                elif role == "primary":
                    primary.setdefault(ev.subject_id, set()).add(artist)
                elif role == "featured":
                    featured.setdefault(ev.subject_id, set()).add(artist)

    popular = set(ranked[:POPULAR_ARTISTS])
    titles = graph.subject_titles

    def usable(song: str) -> bool:
        title = titles.get(song, "")
        return bool(title) and len(title) <= MAX_TITLE_LENGTH

    def by_fame(songs: list[str]) -> tuple[str, ...]:
        return tuple(sorted(songs, key=lambda s: (-degree[next(iter(primary[s]))], s)))

    produced = [
        s
        for s, p in producers.items()
        if usable(s)
        and len(primary.get(s, ())) == 1
        and next(iter(primary[s])) in popular
        and 1 <= len(p) <= MAX_CREDITED
        and not (p & primary[s])
    ]
    featured_songs = [
        s
        for s, f in featured.items()
        if usable(s)
        and len(primary.get(s, ())) == 1
        and len(f) == 1
        and next(iter(primary[s])) in popular
    ]
    worked = [
        a
        for a in ranked[:POPULAR_ARTISTS]
        if sum(1 for n in graph.neighbors[a] if graph.neighbors[a][n].strength(DEFAULT_KINDS) > 0)
        >= MIN_NEIGHBORS
    ]
    producer_artists = sorted(
        {a for ps in producers.values() for a in ps}, key=lambda a: (-degree[a], a)
    )
    performer_artists = sorted(
        {a for fs in (primary, featured) for ps in fs.values() for a in ps},
        key=lambda a: (-degree[a], a),
    )
    return TriviaIndex(
        graph=graph,
        rank=rank,
        ranked=ranked,
        credited={k: frozenset(v) for k, v in credited.items()},
        producers={k: frozenset(v) for k, v in producers.items()},
        primary={k: frozenset(v) for k, v in primary.items()},
        featured={k: frozenset(v) for k, v in featured.items()},
        produced_pool=by_fame(produced)[:150],
        featured_pool=by_fame(featured_songs)[:150],
        worked_pool=tuple(worked),
        producer_artists=tuple(a for a in producer_artists if a in rank)[:DISTRACTOR_POOL],
        performer_artists=tuple(a for a in performer_artists if a in rank)[:DISTRACTOR_POOL],
    )


def _similarity(index: TriviaIndex, a: str, b: str) -> float:
    """How alike two artists look to a listener: genre, era, kind and prominence."""
    nodes = index.graph.nodes
    na, nb = nodes[a], nodes[b]
    score = sum(min(g.share, nb.genre_share(g.genre_id)) for g in na.genres)
    ya, yb = _year(na.begin_date), _year(nb.begin_date)
    if ya is not None and yb is not None:
        score += 0.5 * (1 - min(abs(ya - yb), 30) / 30)
    if na.artist_type and na.artist_type == nb.artist_type:
        score += 0.1
    if na.country and na.country == nb.country:
        score += 0.1
    far = len(index.ranked)
    gap = min(abs(index.rank.get(a, far) - index.rank.get(b, far)), 300)
    return score + 0.3 * (1 - gap / 300)


def _pick_distractors(
    index: TriviaIndex,
    rng: random.Random,
    anchors: Sequence[str],
    pool: Sequence[str],
    banned: set[str],
) -> list[str] | None:
    """Returns three plausible wrong artists, or None if the pool has too few."""
    scored = sorted(
        (-sum(_similarity(index, anchor, c) for anchor in anchors), c)
        for c in pool
        if c not in banned
    )
    close = [c for _, c in scored[:PLAUSIBLE]]
    if len(close) < OPTIONS_PER_QUESTION - 1:
        return None
    return rng.sample(close, OPTIONS_PER_QUESTION - 1)


def _banned_with_identities(graph: ArtistGraph, artists: set[str]) -> set[str]:
    """Adds other identities of the artists: Flying Lotus is also Steven Ellison."""
    return artists | set(graph.other_identities(artists))


def _shuffled(rng: random.Random, answer: str, wrong: list[str]) -> tuple[str, ...]:
    options = [answer, *wrong]
    rng.shuffle(options)
    return tuple(options)


class _Builder:
    """Builds one day's questions from one pool each, without repeating anything."""

    def __init__(self, index: TriviaIndex, labels: LabelFacts | None, rng: random.Random) -> None:
        self.index = index
        self.graph = index.graph
        self.labels = labels
        self.rng = rng
        self.used: set[str] = set()  # artists, songs and labels already in the quiz

    def pools(self) -> dict[QuestionKind, Sequence[str]]:
        """Returns each kind's candidate pool; empty pools mean the kind is unavailable."""
        index = self.index
        pools: dict[QuestionKind, Sequence[str]] = {
            QuestionKind.WHO_PRODUCED: index.produced_pool,
            QuestionKind.WHO_FEATURED: index.featured_pool,
            QuestionKind.WORKED_WITH: index.worked_pool,
        }
        facts = self.labels
        if facts is not None:
            popular = set(index.ranked[:POPULAR_ARTISTS])
            releases = [
                r
                for r, labels in facts.release_labels.items()
                if len(labels) == 1
                and self.graph.subject_titles.get(r)
                and 1 <= len(facts.release_artists.get(r, ())) <= MAX_CREDITED
                and facts.release_artists[r] & popular
            ]
            pools[QuestionKind.WHICH_LABEL] = sorted(
                releases,
                key=lambda r: (
                    min(index.rank.get(a, len(index.ranked)) for a in facts.release_artists[r]),
                    r,
                ),
            )[:150]
        return {k: v for k, v in pools.items() if v}

    def build(self, kind: QuestionKind, pool: Sequence[str], question_id: str) -> Question | None:
        """Returns the first valid question from a random sample of the pool, or None."""
        sample = self.rng.sample(list(pool), min(ATTEMPTS, len(pool)))
        make = {
            QuestionKind.WHO_PRODUCED: self._produced,
            QuestionKind.WHO_FEATURED: self._featured,
            QuestionKind.WORKED_WITH: self._worked_with,
            QuestionKind.WHICH_LABEL: self._label,
        }[kind]
        for candidate in sample:
            question = make(candidate, question_id)
            if question is not None:
                return question
        return None

    def _song(
        self, song: str, question_id: str, kind: QuestionKind, answers: frozenset[str]
    ) -> Question | None:
        index, graph = self.index, self.graph
        (artist,) = index.primary[song]
        if song in self.used or artist in self.used:
            return None
        candidates = sorted(a for a in answers if a not in self.used)
        if not candidates:
            return None
        answer = self.rng.choice(candidates)
        banned = _banned_with_identities(
            graph, set(index.credited.get(song, ())) | {answer, artist}
        )
        pool = (
            index.producer_artists if kind is QuestionKind.WHO_PRODUCED else index.performer_artists
        )
        wrong = _pick_distractors(index, self.rng, [answer], pool, banned)
        if wrong is None:
            return None
        self.used.update((song, artist, answer, *wrong))
        return Question(
            question_id,
            kind,
            _shuffled(self.rng, answer, wrong),
            answer,
            song,
            graph.subject_titles[song],
            artist,
        )

    def _produced(self, song: str, question_id: str) -> Question | None:
        return self._song(song, question_id, QuestionKind.WHO_PRODUCED, self.index.producers[song])

    def _featured(self, song: str, question_id: str) -> Question | None:
        return self._song(song, question_id, QuestionKind.WHO_FEATURED, self.index.featured[song])

    def _worked_with(self, artist: str, question_id: str) -> Question | None:
        index, graph = self.index, self.graph
        if artist in self.used:
            return None
        adjacency = graph.adjacency(DEFAULT_KINDS)
        known = _banned_with_identities(graph, {artist})
        neighbors = sorted(
            (
                n
                for n in adjacency[artist]
                if n in index.rank and n not in known and n not in self.used
            ),
            key=lambda n: (index.rank[n], n),
        )[:8]
        if not neighbors:
            return None
        answer = self.rng.choice(neighbors)
        nearby = bfs_distances(graph.adjacency(ALL_KINDS), artist, max_depth=NEARBY_DEPTH)
        banned = _banned_with_identities(graph, set(nearby) | {answer})
        wrong = _pick_distractors(
            index, self.rng, [answer, answer, artist], index.ranked[:DISTRACTOR_POOL], banned
        )
        if wrong is None:
            return None
        self.used.update((artist, answer, *wrong))
        return Question(
            question_id,
            QuestionKind.WORKED_WITH,
            _shuffled(self.rng, answer, wrong),
            answer,
            "",
            "",
            artist,
        )

    def _label(self, release: str, question_id: str) -> Question | None:
        labels, index, graph = self.labels, self.index, self.graph
        assert labels is not None
        (answer,) = labels.release_labels[release]
        artists = sorted(
            labels.release_artists[release], key=lambda a: index.rank.get(a, len(index.ranked))
        )
        artist = artists[0]
        if release in self.used or artist in self.used or answer in self.used:
            return None
        names = graph.subject_titles
        if not names.get(answer):
            return None
        banned_names = [names[answer].casefold()]
        scored = []
        for label, label_artists in labels.label_artists.items():
            name = names.get(label)
            if (
                label == answer
                or label in self.used
                or not name
                or name.casefold() == banned_names[0]
            ):
                continue
            if label in labels.release_labels[release]:
                continue
            lowered = name.casefold()
            if lowered in banned_names[0] or banned_names[0] in lowered:
                continue  # "Sony Music" next to "Sony Music Latin" would be a coin flip
            fit = max(
                (_similarity(index, artist, a) for a in label_artists if a in graph.nodes),
                default=0.0,
            )
            scored.append((-fit, -len(label_artists), label))
        scored.sort()
        seen: set[str] = set()
        close: list[str] = []
        for _, _, label in scored:  # distinct names only
            key = names[label].casefold()
            if key not in seen:
                seen.add(key)
                close.append(label)
            if len(close) == PLAUSIBLE:
                break
        if len(close) < OPTIONS_PER_QUESTION - 1:
            return None
        wrong = self.rng.sample(close, OPTIONS_PER_QUESTION - 1)
        self.used.update((release, artist, answer, *wrong))
        return Question(
            question_id,
            QuestionKind.WHICH_LABEL,
            _shuffled(self.rng, answer, wrong),
            answer,
            release,
            names[release],
            artist,
        )


def quiz_for(day: date, index: TriviaIndex, labels: LabelFacts | None = None) -> Quiz:
    """Returns the day's quiz: up to five questions, the same for everyone.

    Fewer than five only when the catalog cannot support more fair questions.

    Raises:
        ValueError: The day precedes the launch, or the catalog supports no question.
    """
    if day < LAUNCH_DAY:
        raise ValueError("the first credit check is on the launch day")
    rng = random.Random(stable_int(f"{SEED}:{day.isoformat()}"))  # noqa: S311 - not security
    builder = _Builder(index, labels, rng)
    pools = builder.pools()
    kinds = [k for k in KIND_ORDER if k in pools]
    if not kinds:
        raise ValueError("no credit check questions in this catalog")
    slots = rng.sample(kinds, len(kinds))
    while len(slots) < QUESTIONS_PER_DAY:
        slots.append(rng.choice(kinds))
    questions: list[Question] = []
    for slot in slots[:QUESTIONS_PER_DAY]:
        # Try the slot's kind first, then the others, so a thin pool never shortens the quiz.
        order = [slot, *(k for k in kinds if k is not slot)]
        for kind in order:
            question = builder.build(kind, pools[kind], f"q{len(questions) + 1}")
            if question is not None:
                questions.append(question)
                break
    if not questions:
        raise ValueError("no credit check questions in this catalog")
    return Quiz(day, number_for(day), tuple(questions))


def explain_answer(graph: ArtistGraph, question: Question) -> list[Explanation]:
    """Returns the credits that make the correct option correct (empty for WHICH_LABEL)."""
    if question.kind is QuestionKind.WHICH_LABEL:
        return []
    edge = graph.edge(question.answer, question.artist_id)
    if edge is None:
        return []
    explanations = explain_edge(graph, edge, question.answer, ALL_KINDS)
    if question.kind is QuestionKind.WORKED_WITH:
        explanations = [e for e in explanations if e.kind in DEFAULT_KINDS]
        return explanations[:3]
    return [e for e in explanations if e.subject_id == question.subject_id][:3]


PATH_POOL = 60
PATH_MIN_STEPS = 3
PATH_MAX_STEPS = 5


def path_challenge_pairs(index: TriviaIndex) -> list[tuple[str, str, int]]:
    """Returns (a, b, steps) for well-known artists 3 to 5 connections apart, a < b."""
    adjacency = index.graph.adjacency(DEFAULT_KINDS)
    members = sorted(index.ranked[:PATH_POOL])
    pairs: list[tuple[str, str, int]] = []
    for i, a in enumerate(members):
        distances = bfs_distances(adjacency, a, max_depth=PATH_MAX_STEPS)
        pairs.extend(
            (a, b, distances[b])
            for b in members[i + 1 :]
            if PATH_MIN_STEPS <= distances.get(b, 0) <= PATH_MAX_STEPS
        )
    return pairs


def path_challenge_for(day: date, pairs: Sequence[tuple[str, str, int]]) -> tuple[str, str, int]:
    """Returns the day's "connect these two" pair, the same for everyone.

    Raises:
        ValueError: There are no pairs, or the day precedes the launch.
    """
    if not pairs:
        raise ValueError("no path challenge pairs in this catalog")
    if day < LAUNCH_DAY:
        raise ValueError("the first challenge is on the launch day")
    rng = random.Random(stable_int(f"{SEED}:path:{day.isoformat()}"))  # noqa: S311
    a, b, steps = rng.choice(list(pairs))
    return (a, b, steps) if rng.random() < 0.5 else (b, a, steps)  # noqa: PLR2004
