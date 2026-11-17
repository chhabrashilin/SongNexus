"""Parser first, model second, parser again as the fallback.

The parser answers most questions at once. Only a question it can't place (or
can place only as a plain lookup while it reads like a question) goes to the
model, and only when one is configured. Model interpretations are cached by a
hash of the normalized question, so a popular question costs one model call
per cache lifetime, and concurrent identical questions share one call when the
store coalesces them (the service's response cache does).
"""

from __future__ import annotations

import enum
import hashlib
import json
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Collection
from dataclasses import dataclass
from typing import Any, Protocol

from songnexus.core.ask.intents import Intent, Interpretation
from songnexus.core.ask.llm import LlmError, Provider, validate
from songnexus.core.ask.parser import looks_like_question, parse
from songnexus.core.text import normalize

DEFAULT_CACHE_ENTRIES = 2048
CACHE_TTL_S = 24 * 3600.0


class ModelOutcome(enum.StrEnum):
    """What happened with the model for one question (logged; never the question)."""

    NOT_CONFIGURED = "not_configured"
    NOT_NEEDED = "not_needed"  # the parser was sure
    USED = "used"
    CACHED = "cached"
    FAILED = "failed"  # error, timeout or off-schema output: the parser's result stands


@dataclass(frozen=True)
class Interpreted:
    """An interpretation (None: not understood) and how it was reached."""

    interpretation: Interpretation | None
    model_outcome: ModelOutcome
    model_ms: float | None = None
    failure: str | None = None


class Store(Protocol):
    """Where model interpretations are cached: returns cached bytes or computes and keeps them.

    Returns (bytes, whether they came from the cache). Errors from ``compute``
    propagate and are never stored.
    """

    def get_or_compute(self, key: str, compute: Callable[[], bytes]) -> tuple[bytes, bool]:
        """Returns the cached value for ``key`` or computes it."""
        ...


class MemoryStore:
    """A bounded, thread-safe LRU (used when the service has no shared cache)."""

    def __init__(self, max_entries: int = DEFAULT_CACHE_ENTRIES) -> None:
        self._entries: OrderedDict[str, bytes] = OrderedDict()
        self._max = max_entries
        self._lock = threading.Lock()

    def get_or_compute(self, key: str, compute: Callable[[], bytes]) -> tuple[bytes, bool]:
        """Returns the cached value for ``key`` or computes and keeps it."""
        with self._lock:
            if key in self._entries:
                self._entries.move_to_end(key)
                return self._entries[key], True
        value = compute()
        with self._lock:
            self._entries[key] = value
            self._entries.move_to_end(key)
            while len(self._entries) > self._max:
                self._entries.popitem(last=False)
        return value, False


def to_json(interpretation: Interpretation) -> dict[str, Any]:
    """The model-output form of an interpretation (what ``validate`` reads back)."""
    return {
        "intent": interpretation.intent.value,
        "artists": list(interpretation.artists),
        "songs": [{"title": s.title, "artist": s.artist} for s in interpretation.songs],
        "creditRole": interpretation.credit_role.value if interpretation.credit_role else None,
        "collaborationType": (
            interpretation.collaboration_type.value if interpretation.collaboration_type else None
        ),
        "direction": interpretation.direction.value if interpretation.direction else None,
        "startYear": interpretation.start_year,
        "endYear": interpretation.end_year,
        "genre": interpretation.genre,
        "strongest": interpretation.strongest,
        "text": interpretation.text,
    }


def needs_model(parsed: Interpretation | None, query: str) -> bool:
    """Returns whether the model could do better than the parser on ``query``.

    A parsed intent other than a lookup is trusted. A lookup is trusted for
    plain names, not for text that reads like a question ("what was the
    first song Pharrell produced"), which the parser can only search for.
    """
    if parsed is None:
        return True
    return parsed.intent is Intent.LOOKUP and looks_like_question(query)


def cache_key(provider: Provider, query: str) -> str:
    """A key that identifies the question without containing it."""
    digest = hashlib.sha256(normalize(query).encode()).hexdigest()[:32]
    return f"sn:ask:v1:{provider.name}:{provider.model}:{digest}"


class Interpreter:
    """Turns questions into interpretations."""

    def __init__(
        self,
        provider: Provider | None,
        store: Store | None = None,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self.provider = provider
        self._store = store or MemoryStore()
        self._clock = clock

    def interpret(
        self, query: str, genres: Collection[str] = frozenset(), store: Store | None = None
    ) -> Interpreted:
        """Interprets ``query``: the parser, then the model if needed and available."""
        parsed = parse(query, genres)
        provider = self.provider
        if provider is None:
            return Interpreted(parsed, ModelOutcome.NOT_CONFIGURED)
        if not needs_model(parsed, query):
            return Interpreted(parsed, ModelOutcome.NOT_NEEDED)
        started = self._clock()

        def ask_model() -> bytes:
            interpreted = validate(provider.complete(query), query)
            return json.dumps(to_json(interpreted), separators=(",", ":")).encode()

        try:
            raw, cached = (store or self._store).get_or_compute(
                cache_key(provider, query), ask_model
            )
            # Cached entries pass the same validation as fresh model output.
            from_model = validate(json.loads(raw), query)
        except (LlmError, ValueError) as error:
            elapsed = round((self._clock() - started) * 1000, 1)
            return Interpreted(parsed, ModelOutcome.FAILED, elapsed, str(error))
        elapsed = round((self._clock() - started) * 1000, 1)
        outcome = ModelOutcome.CACHED if cached else ModelOutcome.USED
        return Interpreted(_choose(from_model, parsed), outcome, elapsed)


def _choose(model: Interpretation, parsed: Interpretation | None) -> Interpretation:
    """The model's reading, unless it shrugged and the parser found something to search for."""
    if model.intent is Intent.UNKNOWN and parsed is not None:
        return parsed
    return model
