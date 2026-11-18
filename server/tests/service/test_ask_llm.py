"""The model layer: strict validation, provider request shapes, privacy and failures."""

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from songnexus.core.ask.intents import CreditRole, Intent, SongRef, Source
from songnexus.core.ask.interpreter import Interpreter, MemoryStore, ModelOutcome, needs_model
from songnexus.core.ask.llm import INSTRUCTIONS, SCHEMA, LlmError, grounded, validate
from songnexus.core.ask.parser import parse
from songnexus.service.ask_providers import (
    GeminiProvider,
    OllamaProvider,
    OpenRouterProvider,
    make_provider,
)

QUESTION = "what was the first track where Pharrell produced for Kendrick Lamar"


def output(**fields: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "intent": "UNKNOWN",
        "artists": [],
        "songs": [],
        "creditRole": None,
        "collaborationType": None,
        "direction": None,
        "startYear": None,
        "endYear": None,
        "genre": None,
        "strongest": False,
        "text": None,
    }
    return {**base, **fields}


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_valid_output_becomes_a_model_interpretation() -> None:
    found = validate(output(intent="FIND_PATH", artists=["Pharrell", "Kendrick Lamar"]), QUESTION)
    assert found.intent is Intent.FIND_PATH
    assert found.artists == ("Pharrell", "Kendrick Lamar")
    assert found.source is Source.MODEL


def test_song_credits_default_to_all_credits() -> None:
    found = validate(
        output(intent="SONG_CREDITS", songs=[{"title": "track", "artist": None}]), QUESTION
    )
    assert found.songs == (SongRef("track"),)
    assert found.credit_role is CreditRole.ALL


@pytest.mark.parametrize(
    "raw",
    [
        "FIND_PATH",  # not an object
        [output()],
        output(intent="ANSWER"),  # unknown intent
        output(intent="FIND_PATH", artists=["Pharrell", "Kendrick Lamar"], answer="3 steps"),
        output(intent="FIND_PATH", artists=["Pharrell", "Kendrick Lamar", "Drake"]),
        output(intent="FIND_PATH", artists=["Pharrell"]),  # incomplete
        output(intent="FIND_PATH", artists=[1, 2]),  # wrong types
        output(intent="COLLABORATORS", artists=["Pharrell"], collaborationType="FRIENDS"),
        output(intent="COLLABORATORS", artists=["Pharrell"], startYear="2015"),  # strict int
        output(intent="COLLABORATORS", artists=["Pharrell"], startYear=2019, endYear=2015),
        output(intent="COLLABORATORS", artists=["Pharrell"], startYear=1200),
        output(intent="LOOKUP", text="x" * 200),
        {k: v for k, v in output(intent="UNKNOWN").items() if k != "intent"},
    ],
)
def test_off_schema_output_is_rejected(raw: object) -> None:
    with pytest.raises(LlmError):
        validate(raw, QUESTION)


@pytest.mark.parametrize(
    "raw",
    [
        # Names the question doesn't contain: the model may not add facts.
        output(intent="FIND_PATH", artists=["Pharrell", "Kendrick Lamar"])
        | {"artists": ["Drake", "Kendrick Lamar"]},
        output(intent="COLLABORATORS", artists=["Pharrell"], genre="jazz"),
        output(intent="SONG_CREDITS", songs=[{"title": "HUMBLE.", "artist": "Kendrick Lamar"}]),
    ],
)
def test_names_must_come_from_the_question(raw: object) -> None:
    with pytest.raises(LlmError, match="not in the question"):
        validate(raw, QUESTION)


def test_grounding_tolerates_case_and_small_typos() -> None:
    assert grounded("Kendrick Lamar", "how is kendrik lamar connected to sza")
    assert grounded("SZA", "how is kendrik lamar connected to sza")
    assert not grounded("Drake", "how is kendrik lamar connected to sza")


def test_the_schema_matches_the_validator() -> None:
    assert set(SCHEMA["required"]) == set(output())
    assert SCHEMA["additionalProperties"] is False
    assert set(SCHEMA["properties"]["intent"]["enum"]) == {i.value for i in Intent}


# ---------------------------------------------------------------------------
# Providers: request shapes, privacy, failures
# ---------------------------------------------------------------------------


def client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), timeout=4.0)


def gemini_reply(payload: dict[str, Any]) -> httpx.Response:
    text = json.dumps(payload)
    return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": text}]}}]})


def test_gemini_sends_only_the_question_with_a_schema() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return gemini_reply(output(intent="FIND_PATH", artists=["Pharrell", "Kendrick Lamar"]))

    provider = GeminiProvider("test-key", "gemini-4-hydrogen", client(handler))
    assert validate(provider.complete(QUESTION), QUESTION).intent is Intent.FIND_PATH
    (request,) = seen
    assert request.url.path == "/v1beta/models/gemini-4-hydrogen:generateContent"
    assert request.headers["x-goog-api-key"] == "test-key"
    assert "cookie" not in request.headers
    assert "x-forwarded-for" not in request.headers
    body = json.loads(request.content)
    assert body["contents"] == [{"role": "user", "parts": [{"text": QUESTION}]}]
    assert body["systemInstruction"] == {"parts": [{"text": INSTRUCTIONS}]}
    assert body["generationConfig"]["responseFormat"]["text"] == {
        "mimeType": "APPLICATION_JSON",
        "schema": SCHEMA,
    }
    # Nothing but the fixed instructions, the schema and the question leaves the server.
    assert set(body) == {"systemInstruction", "contents", "generationConfig"}


def test_openrouter_asks_for_strict_json_schema_and_no_data_collection() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        content = json.dumps(output(intent="CONNECTIONS", artists=["Pharrell"]))
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    provider = OpenRouterProvider("or-key", "openrouter/free", client(handler))
    assert validate(provider.complete(QUESTION), QUESTION).intent is Intent.CONNECTIONS
    body = json.loads(seen[0].content)
    assert seen[0].headers["authorization"] == "Bearer or-key"
    assert body["messages"] == [
        {"role": "system", "content": INSTRUCTIONS},
        {"role": "user", "content": QUESTION},
    ]
    assert body["response_format"]["json_schema"]["strict"] is True
    assert body["provider"] == {"require_parameters": True, "data_collection": "deny"}
    assert "user" not in body


def test_ollama_uses_the_schema_as_format() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        content = json.dumps(output(intent="LOOKUP", text="Pharrell"))
        return httpx.Response(200, json={"message": {"content": content}})

    provider = OllamaProvider("llama3.2", client(handler))
    assert validate(provider.complete(QUESTION), QUESTION).text == "Pharrell"
    body = json.loads(seen[0].content)
    assert body["format"] == SCHEMA
    assert body["stream"] is False
    assert seen[0].url.path == "/api/chat"


@pytest.mark.parametrize(
    "respond",
    [
        lambda r: (_ for _ in ()).throw(httpx.ReadTimeout("slow", request=r)),
        lambda r: (_ for _ in ()).throw(httpx.ConnectError("down", request=r)),
        lambda r: httpx.Response(429, json={"error": "quota"}),
        lambda r: httpx.Response(500, text="oops"),
        lambda r: httpx.Response(200, text="not json"),
        lambda r: httpx.Response(200, json={"candidates": []}),
        lambda r: httpx.Response(
            200, json={"candidates": [{"content": {"parts": [{"text": "{not json"}]}}]}
        ),
    ],
)
def test_provider_failures_raise_llm_error(
    respond: Callable[[httpx.Request], httpx.Response],
) -> None:
    provider = GeminiProvider("k", "m", client(respond))
    with pytest.raises(LlmError):
        provider.complete(QUESTION)


def test_errors_never_carry_the_response_body() -> None:
    provider = GeminiProvider("k", "m", client(lambda r: httpx.Response(400, text=QUESTION)))
    with pytest.raises(LlmError) as error:
        provider.complete(QUESTION)
    assert QUESTION not in str(error.value)


def test_no_key_means_no_hosted_model() -> None:
    def factory() -> httpx.Client:
        return client(lambda r: httpx.Response(500))

    def make(name: str, key: str) -> object:
        return make_provider(name, api_key=key, model="", base_url="", http_factory=factory)

    assert make("gemini", "") is None
    assert make("none", "k") is None
    assert make("", "k") is None
    gemini = make_provider("gemini", api_key="k", model="", base_url="", http_factory=factory)
    assert gemini is not None
    assert gemini.model == "gemini-4-hydrogen"
    assert make("ollama", "") is not None  # local, no key
    with pytest.raises(ValueError, match="unknown LLM provider"):
        make("gpt", "k")


# ---------------------------------------------------------------------------
# The interpreter: parser first, model second, fallback, cache
# ---------------------------------------------------------------------------


class FakeProvider:
    name = "fake"
    model = "fake-1"

    def __init__(self, reply: Callable[[str], object]) -> None:
        self.reply = reply
        self.calls: list[str] = []

    def complete(self, query: str) -> object:
        self.calls.append(query)
        return self.reply(query)


def test_parsed_questions_never_reach_the_model() -> None:
    fake = FakeProvider(lambda q: output())
    found = Interpreter(fake).interpret("how is Kendrick Lamar connected to SZA")
    assert found.model_outcome is ModelOutcome.NOT_NEEDED
    assert found.interpretation is not None
    assert found.interpretation.intent is Intent.FIND_PATH
    assert fake.calls == []


def test_the_model_reads_what_the_parser_cannot() -> None:
    fake = FakeProvider(
        lambda q: output(
            intent="COLLABORATORS",
            artists=["Pharrell"],
            collaborationType="PRODUCTION",
            direction="PRODUCED_FOR",
        )
    )
    found = Interpreter(fake).interpret(QUESTION)
    assert found.model_outcome is ModelOutcome.USED
    assert found.interpretation is not None
    assert found.interpretation.source is Source.MODEL
    assert fake.calls == [QUESTION]


def test_a_timeout_falls_back_to_the_parser() -> None:
    def slow(query: str) -> object:
        raise LlmError("timed out")

    question = "what's the meaning of life"
    found = Interpreter(FakeProvider(slow)).interpret(question)
    assert found.model_outcome is ModelOutcome.FAILED
    assert found.failure == "timed out"
    assert found.interpretation == parse(question)


def test_off_schema_model_output_falls_back_to_the_parser() -> None:
    found = Interpreter(FakeProvider(lambda q: {"intent": "ANSWER", "text": "42"})).interpret(
        QUESTION
    )
    assert found.model_outcome is ModelOutcome.FAILED
    assert found.interpretation == parse(QUESTION)


def test_interpretations_are_cached_by_normalized_question() -> None:
    fake = FakeProvider(lambda q: output(intent="CONNECTIONS", artists=["Pharrell"]))
    interpreter = Interpreter(fake, MemoryStore())
    first = interpreter.interpret(QUESTION)
    second = interpreter.interpret(QUESTION.upper() + "?")
    assert first.model_outcome is ModelOutcome.USED
    assert second.model_outcome is ModelOutcome.CACHED
    assert second.interpretation == first.interpretation
    assert len(fake.calls) == 1


def test_failures_are_not_cached() -> None:
    replies = iter([LlmError("timed out"), output(intent="CONNECTIONS", artists=["Pharrell"])])

    def flaky(query: str) -> object:
        reply = next(replies)
        if isinstance(reply, Exception):
            raise reply
        return reply

    interpreter = Interpreter(FakeProvider(flaky))
    assert interpreter.interpret(QUESTION).model_outcome is ModelOutcome.FAILED
    assert interpreter.interpret(QUESTION).model_outcome is ModelOutcome.USED


def test_a_model_shrug_keeps_the_parsers_search() -> None:
    question = "who is the best producer, Pharrell or Timbaland?"
    found = Interpreter(FakeProvider(lambda q: output())).interpret(question)
    assert found.interpretation == parse(question)


def test_without_a_model_the_parser_is_the_interpreter() -> None:
    found = Interpreter(None).interpret(QUESTION)
    assert found.model_outcome is ModelOutcome.NOT_CONFIGURED
    assert found.interpretation == parse(QUESTION)


def test_only_question_shaped_lookups_need_the_model() -> None:
    assert not needs_model(parse("Kendrick Lamar"), "Kendrick Lamar")
    assert needs_model(parse("who is the best producer"), "who is the best producer")
    assert needs_model(None, "anything")
