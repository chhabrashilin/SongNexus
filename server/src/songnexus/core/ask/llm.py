"""The optional model layer: a question in, one strictly validated ``Interpretation`` out.

The model only classifies: it picks one of the fixed intents and copies entity
names out of the question. It never answers, so it cannot state a fact about
music. Its output is checked against the schema below, and every name must be
grounded in the question (a model can't add an artist the person didn't name);
anything else is discarded and the parser's result stands.

Providers (request shapes checked against each provider's documentation in
November 2026):

- ``gemini``: Google Gemini API ``models/{model}:generateContent`` with
  ``generationConfig.responseFormat.text`` (``APPLICATION_JSON`` plus a JSON
  Schema). Default model ``gemini-4-hydrogen`` (free tier).
- ``openrouter``: OpenAI-compatible ``/chat/completions`` with
  ``response_format: {type: json_schema}`` and ``provider.require_parameters``
  so only endpoints that enforce the schema are used. Default model
  ``openrouter/free`` (routes to a free model).
- ``ollama``: a local ``/api/chat`` with ``format`` set to the JSON Schema.

Only the question text is sent: no user, session, history or address.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any, Literal, Protocol

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from songnexus.core.ask.intents import (
    MAX_MENTION_LENGTH,
    CreditRole,
    Intent,
    Interpretation,
    SongRef,
    Source,
)
from songnexus.core.graph.collaborations import CollaborationType, ProductionDirection
from songnexus.core.text import normalize, string_similarity

PROVIDERS = ("gemini", "openrouter", "ollama")
DEFAULT_MODELS = {
    "gemini": "gemini-4-hydrogen",
    "openrouter": "openrouter/free",
    "ollama": "llama3.2",
}
DEFAULT_BASE_URLS = {
    "gemini": "https://generativelanguage.googleapis.com/v1beta",
    "openrouter": "https://openrouter.ai/api/v1",
    "ollama": "http://127.0.0.1:11434",
}
MAX_RESPONSE_BYTES = 16_384
MIN_WORD = 3
WORD_SIMILARITY = 0.8
HTTP_OK = 200

INSTRUCTIONS = """\
You turn one question about music credits into JSON for a search engine. You never answer
the question and never add information. Pick exactly one intent:
- FIND_PATH: how two artists are connected ("how is A linked to B", "did A work with B").
- COMPARE_ARTISTS: compare two artists.
- COMPARE_SONGS: compare two songs.
- SONG_CREDITS: who produced / is featured on / performed / is credited on one song.
  creditRole is PRODUCER, FEATURED, PERFORMER or ALL.
- COLLABORATORS: one artist's collaborators. collaborationType is FEATURE (performed
  together), PRODUCTION, BAND (bands and projects) or CREDIT (other credits), or null for
  all. For PRODUCTION, direction is PRODUCED_BY (who produced the artist) or PRODUCED_FOR
  (whom the artist produced). startYear, endYear and genre narrow it when the question says so.
- CONNECTIONS: artists like / similar to / connected to one artist.
- LOOKUP: the question just names an artist or song; put that name in text.
- UNKNOWN: anything else (opinions, lyrics, charts, news, anything not about credits).
Copy artist names and song titles exactly as they are written in the question. Never
correct, expand or guess a name, and never name anyone the question does not name.
Leave unused fields empty ([] or null). strongest is true only if the question asks for
the strongest links."""


def _nullable(kind: str, **extra: Any) -> dict[str, Any]:
    return {"type": [kind, "null"], **extra}


def _enum_or_null(values: list[str]) -> dict[str, Any]:
    return {"type": ["string", "null"], "enum": [*values, None]}


SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "intent": {"type": "string", "enum": [i.value for i in Intent]},
        "artists": {
            "type": "array",
            "items": {"type": "string", "maxLength": MAX_MENTION_LENGTH},
            "maxItems": 2,
        },
        "songs": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "maxLength": MAX_MENTION_LENGTH},
                    "artist": _nullable("string", maxLength=MAX_MENTION_LENGTH),
                },
                "required": ["title", "artist"],
                "additionalProperties": False,
            },
            "maxItems": 2,
        },
        "creditRole": _enum_or_null([r.value for r in CreditRole]),
        "collaborationType": _enum_or_null([t.value for t in CollaborationType]),
        "direction": _enum_or_null(
            [ProductionDirection.PRODUCED_BY.value, ProductionDirection.PRODUCED_FOR.value]
        ),
        "startYear": _nullable("integer", minimum=1900, maximum=2100),
        "endYear": _nullable("integer", minimum=1900, maximum=2100),
        "genre": _nullable("string", maxLength=MAX_MENTION_LENGTH),
        "strongest": {"type": "boolean"},
        "text": _nullable("string", maxLength=MAX_MENTION_LENGTH),
    },
    "required": [
        "intent",
        "artists",
        "songs",
        "creditRole",
        "collaborationType",
        "direction",
        "startYear",
        "endYear",
        "genre",
        "strongest",
        "text",
    ],
    "additionalProperties": False,
}


class LlmError(RuntimeError):
    """The model failed, timed out or answered off-schema. Callers fall back to the parser."""


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

Mention = Field(min_length=1, max_length=MAX_MENTION_LENGTH)


class _Song(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    title: str = Mention
    artist: str | None = Field(default=None, max_length=MAX_MENTION_LENGTH)


class _Output(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    intent: Literal[
        "FIND_PATH",
        "COMPARE_ARTISTS",
        "COMPARE_SONGS",
        "SONG_CREDITS",
        "COLLABORATORS",
        "CONNECTIONS",
        "LOOKUP",
        "UNKNOWN",
    ]
    artists: list[str] = Field(default_factory=list, max_length=2)
    songs: list[_Song] = Field(default_factory=list, max_length=2)
    creditRole: Literal["PRODUCER", "FEATURED", "PERFORMER", "ALL"] | None = None  # noqa: N815
    collaborationType: Literal["FEATURE", "PRODUCTION", "BAND", "CREDIT"] | None = None  # noqa: N815
    direction: Literal["PRODUCED_BY", "PRODUCED_FOR"] | None = None
    startYear: int | None = Field(default=None, ge=1900, le=2100)  # noqa: N815
    endYear: int | None = Field(default=None, ge=1900, le=2100)  # noqa: N815
    genre: str | None = Field(default=None, max_length=MAX_MENTION_LENGTH)
    strongest: bool = False
    text: str | None = Field(default=None, max_length=MAX_MENTION_LENGTH)


_TOKEN = re.compile(r"\w+")


def grounded(mention: str, query: str) -> bool:
    """Returns whether a name appears in the question (allowing small typos and case).

    Every word of three or more characters in the mention must closely match a
    word of the question, so a model can copy names but never introduce one.
    """
    words = [w for w in normalize(mention).split() if len(w) >= MIN_WORD] or normalize(
        mention
    ).split()
    if not words:
        return False
    question = normalize(query)
    if normalize(mention) in question:
        return True
    query_words = question.split()
    return all(any(string_similarity(w, q) >= WORD_SIMILARITY for q in query_words) for w in words)


def validate(raw: object, query: str) -> Interpretation:
    """Turns a model's output into an Interpretation, or raises LlmError.

    Rejects anything off-schema (unknown fields or values, wrong types, too
    many names), names not found in the question, and incomplete intents.
    """
    try:
        out = _Output.model_validate(raw)
    except ValidationError as error:
        raise LlmError(f"off-schema output ({error.error_count()} errors)") from None
    names = [*out.artists, *(s.title for s in out.songs)]
    names += [s.artist for s in out.songs if s.artist]
    names += [x for x in (out.genre, out.text) if x]
    if any(not n.strip() or not grounded(n, query) for n in names):
        raise LlmError("a name in the output is not in the question")
    if out.startYear and out.endYear and out.startYear > out.endYear:
        raise LlmError("year range is reversed")
    intent = Intent(out.intent)
    interpretation = Interpretation(
        intent=intent,
        artists=tuple(a.strip() for a in out.artists),
        songs=tuple(
            SongRef(s.title.strip(), s.artist.strip() if s.artist else None) for s in out.songs
        ),
        credit_role=CreditRole(out.creditRole) if out.creditRole else None,
        collaboration_type=(
            CollaborationType(out.collaborationType) if out.collaborationType else None
        ),
        direction=ProductionDirection(out.direction) if out.direction else None,
        start_year=out.startYear,
        end_year=out.endYear,
        genre=out.genre.strip() if out.genre else None,
        strongest=out.strongest,
        text=out.text.strip() if out.text else None,
        source=Source.MODEL,
    )
    if intent is Intent.SONG_CREDITS and interpretation.credit_role is None:
        interpretation = replace(interpretation, credit_role=CreditRole.ALL)
    if not interpretation.is_complete():
        raise LlmError(f"incomplete {intent.value} interpretation")
    return interpretation


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------


class Provider(Protocol):
    """A model that turns a question into raw (unvalidated) intent JSON."""

    name: str
    model: str

    def complete(self, query: str) -> object:
        """Returns the model's parsed JSON output. Raises LlmError on any failure."""
        ...


def _post(http: httpx.Client, url: str, *, headers: dict[str, str], body: dict[str, Any]) -> Any:
    try:
        response = http.post(url, headers=headers, json=body)
    except httpx.TimeoutException:
        raise LlmError("timed out") from None
    except httpx.HTTPError as error:
        raise LlmError(f"request failed: {type(error).__name__}") from None
    if response.status_code != HTTP_OK:
        # The body may echo the question, so only the status is kept.
        raise LlmError(f"HTTP {response.status_code}")
    if len(response.content) > MAX_RESPONSE_BYTES * 4:
        raise LlmError("response too large")
    try:
        return response.json()
    except ValueError:
        raise LlmError("response is not JSON") from None


def _json_text(text: object) -> object:
    if not isinstance(text, str) or len(text) > MAX_RESPONSE_BYTES:
        raise LlmError("no text in the response")
    try:
        return json.loads(text)
    except ValueError:
        raise LlmError("model output is not JSON") from None


@dataclass
class GeminiProvider:
    """Google Gemini API (``generateContent`` with a response JSON Schema)."""

    api_key: str
    model: str
    http: httpx.Client
    base_url: str = DEFAULT_BASE_URLS["gemini"]
    name: str = "gemini"

    def request(self, query: str) -> tuple[str, dict[str, str], dict[str, Any]]:
        """Returns the URL, headers and body sent for ``query`` (for tests and review)."""
        return (
            f"{self.base_url.rstrip('/')}/models/{self.model}:generateContent",
            {"x-goog-api-key": self.api_key, "Content-Type": "application/json"},
            {
                "systemInstruction": {"parts": [{"text": INSTRUCTIONS}]},
                "contents": [{"role": "user", "parts": [{"text": query}]}],
                "generationConfig": {
                    "temperature": 0,
                    "maxOutputTokens": 512,
                    "responseFormat": {"text": {"mimeType": "APPLICATION_JSON", "schema": SCHEMA}},
                },
            },
        )

    def complete(self, query: str) -> object:
        """Asks Gemini to classify ``query``."""
        url, headers, body = self.request(query)
        data = _post(self.http, url, headers=headers, body=body)
        try:
            text = data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError):
            raise LlmError("unexpected response shape") from None
        return _json_text(text)


@dataclass
class OpenRouterProvider:
    """OpenRouter (OpenAI-compatible chat completions with ``json_schema`` output)."""

    api_key: str
    model: str
    http: httpx.Client
    base_url: str = DEFAULT_BASE_URLS["openrouter"]
    name: str = "openrouter"

    def request(self, query: str) -> tuple[str, dict[str, str], dict[str, Any]]:
        """Returns the URL, headers and body sent for ``query``."""
        return (
            f"{self.base_url.rstrip('/')}/chat/completions",
            {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": INSTRUCTIONS},
                    {"role": "user", "content": query},
                ],
                "temperature": 0,
                "max_tokens": 512,
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {"name": "interpretation", "strict": True, "schema": SCHEMA},
                },
                # Only endpoints that honor the schema; never ones that keep prompts.
                "provider": {"require_parameters": True, "data_collection": "deny"},
            },
        )

    def complete(self, query: str) -> object:
        """Asks the OpenRouter model to classify ``query``."""
        url, headers, body = self.request(query)
        data = _post(self.http, url, headers=headers, body=body)
        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise LlmError("unexpected response shape") from None
        return _json_text(text)


@dataclass
class OllamaProvider:
    """A local Ollama server (``/api/chat`` with ``format`` set to the schema)."""

    model: str
    http: httpx.Client
    base_url: str = DEFAULT_BASE_URLS["ollama"]
    name: str = "ollama"

    def request(self, query: str) -> tuple[str, dict[str, str], dict[str, Any]]:
        """Returns the URL, headers and body sent for ``query``."""
        return (
            f"{self.base_url.rstrip('/')}/api/chat",
            {"Content-Type": "application/json"},
            {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": INSTRUCTIONS},
                    {"role": "user", "content": query},
                ],
                "stream": False,
                "format": SCHEMA,
                "options": {"temperature": 0},
            },
        )

    def complete(self, query: str) -> object:
        """Asks the local model to classify ``query``."""
        url, headers, body = self.request(query)
        data = _post(self.http, url, headers=headers, body=body)
        try:
            text = data["message"]["content"]
        except (KeyError, TypeError):
            raise LlmError("unexpected response shape") from None
        return _json_text(text)


def make_provider(
    provider: str,
    *,
    api_key: str,
    model: str,
    base_url: str,
    http_factory: Callable[[], httpx.Client],
) -> Provider | None:
    """Builds the configured provider, or None (parser only).

    Hosted providers need a key; without one there is no model. Ollama runs
    locally and needs none.

    Raises:
        ValueError: An unknown provider name.
    """
    name = provider.strip().lower()
    if not name or name == "none":
        return None
    if name not in PROVIDERS:
        raise ValueError(f"unknown LLM provider {provider!r}; choose from {PROVIDERS}")
    chosen = model or DEFAULT_MODELS[name]
    url = base_url or DEFAULT_BASE_URLS[name]
    if name == "ollama":
        return OllamaProvider(chosen, http_factory(), url)
    if not api_key:
        return None
    if name == "gemini":
        return GeminiProvider(api_key, chosen, http_factory(), url)
    return OpenRouterProvider(api_key, chosen, http_factory(), url)
