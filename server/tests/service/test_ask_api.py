"""AskCatalog (ADR 0008): questions answered from the catalog, with and without a model."""

import json
import logging
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from songnexus.catalog.canonicalize import build_batch
from songnexus.catalog.ingest import ingest_snapshot
from songnexus.catalog.snapshot import write_snapshot
from songnexus.config import Settings
from songnexus.core import ids
from songnexus.core.ask.interpreter import Interpreter
from songnexus.core.ask.llm import GeminiProvider
from songnexus.service.app import build_state, create_app
from songnexus.storage import migrate
from songnexus.storage.db import make_engine
from tests.catalog import fixtures as fx

ALICE = ids.artist_id("mb-alice")
BOB = ids.artist_id("mb-bob")
BAND = ids.artist_id("mb-band")
CAROL = ids.artist_id("mb-carol")


def _recording(mbid: str) -> str:
    batch = build_batch(fx.small_catalog())
    (row,) = (
        r
        for r in batch.mappings.values()
        if r["entity_type"] == "recording" and r["source_entity_id"] == mbid
    )
    return str(row["entity_id"])


SONG = _recording("rec-1")


@pytest.fixture(scope="module")
def settings(tmp_path_factory: pytest.TempPathFactory) -> Settings:
    root = tmp_path_factory.mktemp("ask")
    snapshot = root / "snapshot.jsonl.gz"
    write_snapshot(fx.small_catalog(), snapshot)
    url = f"sqlite:///{root / 'catalog.db'}"
    engine = make_engine(url)
    migrate.upgrade(engine)
    ingest_snapshot(engine, snapshot)
    return Settings(
        database_url=url,
        data_dir=Path(root),
        log_json=False,
        read_model_refresh_s=3600,
        llm_provider="gemini",
        llm_api_key="",  # no key: the parser alone
    )


@pytest.fixture(scope="module")
def app(settings: Settings) -> FastAPI:
    return create_app(settings, build_state(settings))


@pytest.fixture(scope="module")
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def with_interpreter(app: FastAPI) -> Iterator[Callable[[Interpreter], None]]:
    """Swaps the app's interpreter for one test, then restores the parser-only one."""
    original = getattr(app.state, "ask_interpreter", None)

    def use(interpreter: Interpreter) -> None:
        app.state.ask_interpreter = interpreter

    yield use
    app.state.ask_interpreter = original


def ask(client: TestClient, query: str, **extra: Any) -> dict[str, Any]:
    response = client.post("/v1/catalog:ask", json={"query": query, **extra})
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def model_output(**fields: Any) -> dict[str, Any]:
    return {
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
    } | fields


def gemini(handler: Callable[[httpx.Request], httpx.Response]) -> GeminiProvider:
    http = httpx.Client(transport=httpx.MockTransport(handler), timeout=4.0)
    return GeminiProvider("test-key", "gemini-4-hydrogen", http)


def reply(payload: dict[str, Any]) -> httpx.Response:
    text = json.dumps(payload)
    return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": text}]}}]})


# ---------------------------------------------------------------------------
# Without a model
# ---------------------------------------------------------------------------


def test_a_path_question_is_answered_from_the_graph(client: TestClient) -> None:
    body = ask(client, "How is Bob connected to The Band?")
    assert body["interpretation"] == body["interpretation"] | {
        "intent": "FIND_PATH",
        "interpretedBy": "PARSER",
    }
    assert body["answer"] == {
        "messageId": "ask.answer.path",
        "params": {"a": "Bob", "b": "The Band", "steps": 2},
    }
    assert [e["status"] for e in body["entities"]] == ["MATCHED", "MATCHED"]
    assert [r["artist"]["name"] for r in body["results"]] == [f"artists/{ALICE}", f"artists/{BAND}"]
    # Every step carries evidence with a source to check it against.
    for row in body["results"]:
        (evidence,) = row["evidence"]
        assert evidence["sources"], evidence
    url = urlsplit(body["destination"])
    assert url.path == "/six-degrees"
    assert parse_qs(url.query) == {"from": [BOB], "to": [BAND], "mode": ["FEWEST_STEPS"]}
    assert {a["displayName"] for a in body["artists"]} >= {"Alice", "Bob", "The Band"}
    assert body["model"] == {"configured": False, "used": False, "provider": None, "model": None}


def test_a_direct_connection_says_so(client: TestClient) -> None:
    body = ask(client, "did Bob ever work with Alice")
    assert body["answer"]["messageId"] == "ask.answer.pathDirect"


def test_who_produced_a_song_names_the_credited_producer(client: TestClient) -> None:
    body = ask(client, 'who produced "Song" by Alice?')
    assert body["interpretation"]["intent"] == "SONG_CREDITS"
    assert body["interpretation"]["creditRole"] == "PRODUCER"
    assert body["answer"]["messageId"] == "ask.answer.song.PRODUCER"
    assert body["answer"]["params"] == {"song": "Song", "count": 1, "names": ["Carol"], "more": 0}
    (row,) = body["results"]
    assert row["artist"]["displayName"] == "Carol"
    assert row["role"] == "producer"
    assert row["sources"][0]["source"] == "musicbrainz"
    assert body["destination"] == f"/song/{SONG}"


def test_who_is_featured_on_a_song(client: TestClient) -> None:
    body = ask(client, "who is featured on Song")
    assert body["answer"]["params"]["names"] == ["Bob"]


def test_compare_two_artists(client: TestClient) -> None:
    body = ask(client, "Alice vs Bob")
    assert body["answer"]["messageId"] == "ask.answer.compare"
    assert body["answer"]["params"]["steps"] == 1
    assert body["destination"] == f"/compare?a={ALICE}&b={BOB}"


def test_compare_two_songs(client: TestClient) -> None:
    body = ask(client, 'compare songs "Song" and "Other Song"')
    assert body["interpretation"]["intent"] == "COMPARE_SONGS"
    assert body["answer"]["params"]["shared"] == 1  # Alice is the primary artist of both
    assert body["destination"].startswith("/compare/songs?a=")


def test_collaborators_link_to_the_collaborations_page(client: TestClient) -> None:
    body = ask(client, "Alice's producers")
    assert body["answer"]["messageId"] == "ask.answer.collab.PRODUCED_BY"
    assert body["answer"]["params"]["names"] == ["Carol"]
    assert body["results"][0]["count"] == 1
    assert body["destination"] == (
        f"/artist/{ALICE}/collaborations?type=PRODUCTION&direction=PRODUCED_BY"
    )


def test_an_unknown_genre_is_said_plainly(client: TestClient) -> None:
    body = ask(client, "Alice's polka collaborators")
    assert body["answer"] == {
        "messageId": "ask.answer.genreNotFound",
        "params": {"genre": "polka"},
    }


def test_artists_like_opens_the_connection_web(client: TestClient) -> None:
    body = ask(client, "artists like Alice")
    assert body["answer"]["messageId"] == "ask.answer.connections"
    assert body["destination"] == f"/explore/{ALICE}"


def test_a_name_not_in_our_data_is_never_guessed(client: TestClient) -> None:
    body = ask(client, "how is Zyxwvut Qqq connected to Alice")
    assert body["answer"] == {"messageId": "ask.answer.notFound", "params": {"name": "Zyxwvut Qqq"}}
    assert body["destination"] is None
    assert body["results"] == []


def test_a_plain_name_is_a_lookup(client: TestClient) -> None:
    body = ask(client, "alice")
    assert body["answer"] == {"messageId": "ask.answer.lookup.artist", "params": {"name": "Alice"}}
    assert body["destination"] == f"/artist/{ALICE}"


def test_without_a_model_an_unreadable_question_says_so(client: TestClient) -> None:
    body = ask(client, "which album won the most grammys in the history of the awards")
    assert body["interpretation"]["intent"] == "UNKNOWN"
    assert body["interpretation"]["interpretedBy"] == "NONE"
    assert body["answer"]["messageId"] == "ask.answer.unknown"


def test_requests_are_validated(client: TestClient) -> None:
    assert client.post("/v1/catalog:ask", json={"query": ""}).status_code == 400
    assert client.post("/v1/catalog:ask", json={"query": "x" * 121}).status_code == 400
    assert client.post("/v1/catalog:ask", json={"query": "   "}).status_code == 400
    bad_choice = client.post("/v1/catalog:ask", json={"query": "alice", "choices": ["nope"]})
    assert bad_choice.status_code == 400


def test_answers_are_private_and_the_question_is_never_logged(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    question = "how is Bob connected to Carol"
    with caplog.at_level(logging.INFO):
        response = client.post("/v1/catalog:ask", json={"query": question})
    assert response.headers["cache-control"] == "private, no-store"
    records = [r for r in caplog.records if r.getMessage() == "ask"]
    assert records
    assert records[0].__dict__["intent"] == "FIND_PATH"
    for record in caplog.records:
        assert "Bob connected" not in record.getMessage()
        assert all("Bob connected" not in str(v) for v in record.__dict__.values())


def test_the_kill_switch_turns_ask_off(settings: Settings) -> None:
    off = settings.model_copy(update={"flags": {"ask": False}})
    with TestClient(create_app(off, build_state(off))) as client:
        assert client.get("/v1/config").json()["flags"]["ask"] is False
        response = client.post("/v1/catalog:ask", json={"query": "alice"})
    assert response.status_code == 503
    assert response.json()["error"]["details"][0]["reason"] == "FLAG_OFF"


# ---------------------------------------------------------------------------
# With a (fake) model
# ---------------------------------------------------------------------------


def test_the_model_interprets_and_our_data_answers(
    client: TestClient, with_interpreter: Callable[[Interpreter], None]
) -> None:
    sent: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return reply(model_output(intent="FIND_PATH", artists=["Bob", "The Band"]))

    with_interpreter(Interpreter(gemini(handler)))
    question = "I keep wondering whether Bob and The Band ever crossed paths somehow"
    body = ask(client, question)
    assert body["interpretation"]["interpretedBy"] == "MODEL"
    assert body["answer"]["messageId"] == "ask.answer.path"
    assert body["answer"]["params"]["steps"] == 2  # from the graph, not the model
    assert body["model"] == {
        "configured": True,
        "used": True,
        "provider": "gemini",
        "model": "gemini-4-hydrogen",
    }
    # Privacy: the request carries the question and our fixed instructions, nothing else.
    (request,) = sent
    payload = json.loads(request.content)
    assert payload["contents"] == [{"role": "user", "parts": [{"text": question}]}]
    assert "cookie" not in request.headers
    assert set(request.headers) <= {
        "host",
        "accept",
        "accept-encoding",
        "connection",
        "user-agent",
        "content-length",
        "content-type",
        "x-goog-api-key",
    }


def test_a_model_timeout_falls_back_to_the_parser(
    client: TestClient, with_interpreter: Callable[[Interpreter], None]
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    with_interpreter(Interpreter(gemini(handler)))
    body = ask(client, "who is Alice")  # question-shaped, so the model is tried
    assert body["model"]["used"] is False
    assert body["interpretation"]["interpretedBy"] == "PARSER"
    assert body["answer"]["messageId"] == "ask.answer.lookup.artist"


def test_a_model_naming_someone_else_is_ignored(
    client: TestClient, with_interpreter: Callable[[Interpreter], None]
) -> None:
    with_interpreter(
        Interpreter(gemini(lambda r: reply(model_output(intent="CONNECTIONS", artists=["Carol"]))))
    )
    body = ask(client, "who is Alice")
    assert body["model"]["used"] is False
    assert body["entities"][0]["match"]["displayName"] == "Alice"


def test_parsed_questions_skip_the_model(
    client: TestClient, with_interpreter: Callable[[Interpreter], None]
) -> None:
    sent: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return reply(model_output())

    with_interpreter(Interpreter(gemini(handler)))
    body = ask(client, "Alice vs Bob")
    assert body["model"] == body["model"] | {"configured": True, "used": False}
    assert sent == []
