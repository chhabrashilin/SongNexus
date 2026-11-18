"""Model providers for Ask (ADR 0008): the HTTP half of ``core.ask.llm``.

``core`` stays pure (no network): it owns the instructions, the schema, the
validation and the ``Provider`` interface. This module implements that interface
for the Gemini API, OpenRouter and Ollama. Only the question text, our fixed
instructions and the schema are sent; never an identity.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx

from songnexus.core.ask.llm import (
    DEFAULT_BASE_URLS,
    DEFAULT_MODELS,
    HTTP_OK,
    INSTRUCTIONS,
    MAX_RESPONSE_BYTES,
    PROVIDERS,
    SCHEMA,
    LlmError,
    Provider,
)


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
