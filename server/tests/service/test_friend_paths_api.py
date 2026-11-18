"""Friend paths through the API: who may see whose top artists, and what comes back."""

import contextlib
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from songnexus.config import Settings
from songnexus.core import ids
from songnexus.service.app import build_state, create_app
from songnexus.service.deps import AppState
from songnexus.storage import models as m
from songnexus.storage import social_repository as social
from songnexus.storage.db import session_scope
from tests.service.databases import fresh_database_url, migrated_with_catalog
from tests.service.test_identity import FakeVerifier, reason, sign_in

ALICE = ids.artist_id("mb-alice")
BOB = ids.artist_id("mb-bob")
CAROL = ids.artist_id("mb-carol")
BAND = ids.artist_id("mb-band")


@pytest.fixture
def stack(tmp_path: Path) -> Iterator[tuple[AppState, contextlib.ExitStack]]:
    url = fresh_database_url(tmp_path)
    migrated_with_catalog(url, tmp_path)
    settings = Settings(database_url=url, log_json=False, read_model_refresh_s=3600)
    built = build_state(settings)
    built.verifier = FakeVerifier()
    with contextlib.ExitStack() as clients:
        yield built, clients
    built.engine.dispose()


def person(
    stack: tuple[AppState, contextlib.ExitStack], uid: str, artists: list[str]
) -> tuple[TestClient, str]:
    state, clients = stack
    c = clients.enter_context(
        TestClient(create_app(state.settings, state), base_url="https://testserver")
    )
    user = sign_in(c, uid)["user"].removeprefix("users/")
    assert c.patch("/v1/users/me/socialProfile", json={"displayName": uid}).status_code == 200
    with session_scope(state.engine) as session:
        for plays, artist_id in enumerate(reversed(artists), start=1):
            session.add(
                m.ListeningTally(
                    user_id=user,
                    provider="LISTENBRAINZ",
                    artist_id=artist_id,
                    plays=plays * 10,
                    last_played_at=None,
                )
            )
    return c, user


def share(c: TestClient, on: bool = True) -> None:
    response = c.patch("/v1/users/me/socialProfile", json={"shareTopArtists": on})
    assert response.status_code == 200, response.text
    assert response.json()["shareTopArtists"] is on


def befriend(stack: tuple[AppState, contextlib.ExitStack], a: str, b: str) -> None:
    with session_scope(stack[0].engine) as session:
        social.befriend(session, a, b, datetime.now(UTC))


def paths(c: TestClient, friend: str) -> object:
    return c.get(f"/v1/users/me/friends/{friend}/paths")


def test_sharing_is_off_by_default_and_needs_a_display_name(
    stack: tuple[AppState, contextlib.ExitStack],
) -> None:
    ana, _ = person(stack, "ana", [BOB])
    assert ana.get("/v1/users/me/socialProfile").json()["shareTopArtists"] is False
    state, clients = stack
    fresh = clients.enter_context(
        TestClient(create_app(state.settings, state), base_url="https://testserver")
    )
    sign_in(fresh, "nameless")
    refused = fresh.patch("/v1/users/me/socialProfile", json={"shareTopArtists": True})
    assert reason(refused) == "DISPLAY_NAME_REQUIRED"
    assert fresh.patch("/v1/users/me/socialProfile", json={}).status_code == 400


def test_permissions_in_order(stack: tuple[AppState, contextlib.ExitStack]) -> None:
    ana, ana_id = person(stack, "ana", [BOB])
    ben, ben_id = person(stack, "ben", [CAROL, BAND])
    share(ana)
    share(ben)
    assert reason(paths(ana, ben_id)) == "FRIEND_NOT_FOUND"  # not friends
    befriend(stack, ana_id, ben_id)
    share(ana, False)
    assert reason(paths(ana, ben_id)) == "VIEWER_NOT_SHARING"
    share(ana)
    share(ben, False)
    response = paths(ana, ben_id)
    assert response.status_code == 400
    assert reason(response) == "FRIEND_NOT_SHARING"
    share(ben)
    assert paths(ana, ben_id).status_code == 200
    other = ana.get(f"/v1/users/{ben_id}/friends/{ana_id}/paths")
    assert reason(other) == "NOT_YOUR_RESOURCE"
    # Blocking ends it, and looks exactly like "not a friend".
    assert (
        ben.post("/v1/users/me/blockedUsers", json={"user": f"users/{ana_id}"}).status_code == 200
    )
    assert reason(paths(ana, ben_id)) == "FRIEND_NOT_FOUND"


def test_paths_shared_artists_and_collaborators(
    stack: tuple[AppState, contextlib.ExitStack],
) -> None:
    ana, ana_id = person(stack, "ana", [BOB, BAND])
    ben, ben_id = person(stack, "ben", [CAROL, BAND])
    for c in (ana, ben):
        share(c)
    befriend(stack, ana_id, ben_id)
    response = paths(ana, ben_id)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["friend"] == {"user": f"users/{ben_id}", "displayName": "ben"}
    assert [a["name"] for a in body["viewerArtists"]] == [f"artists/{BOB}", f"artists/{BAND}"]
    assert [a["name"] for a in body["sharedArtists"]] == [f"artists/{BAND}"]
    assert body["paths"], body
    first = body["paths"][0]
    assert first["fromArtist"]["name"] == f"artists/{BOB}"
    assert first["toArtist"]["name"] == f"artists/{CAROL}"
    assert all(step["evidence"] for step in first["steps"])
    assert f"artists/{ALICE}" in {c["artist"]["name"] for c in body["sharedCollaborators"]}
    assert body["demoData"] is False


def test_blocked_artists_never_appear(stack: tuple[AppState, contextlib.ExitStack]) -> None:
    ana, ana_id = person(stack, "ana", [BAND])
    ben, ben_id = person(stack, "ben", [ALICE, CAROL])
    for c in (ana, ben):
        share(c)
    befriend(stack, ana_id, ben_id)
    assert ana.post(
        "/v1/users/me/blockedArtists", json={"artist": f"artists/{ALICE}"}
    ).status_code in {
        200,
        201,
    }
    body = paths(ana, ben_id).json()
    text = str(body)
    assert ALICE not in text
    assert [a["name"] for a in body["friendArtists"]] == [f"artists/{CAROL}"]


def test_no_top_artists(stack: tuple[AppState, contextlib.ExitStack]) -> None:
    ana, ana_id = person(stack, "ana", [BOB])
    ben, ben_id = person(stack, "ben", [])
    for c in (ana, ben):
        share(c)
    befriend(stack, ana_id, ben_id)
    response = paths(ana, ben_id)
    assert reason(response) == "NO_TOP_ARTISTS"
    assert response.json()["error"]["details"][0]["metadata"] == {"side": "friend"}
