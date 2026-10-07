"""Identity and user-data security tests (plan §21, M4-05).

Covers AC-18.1-18.4, AC-17.1-17.2 and AC-9.1 against the real application with
a fake ID-token verifier (tokens are "uid:<firebase uid>").
"""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from songnexus.catalog.ingest import ingest_snapshot
from songnexus.catalog.musicbrainz.snapshot import write_snapshot
from songnexus.config import Settings
from songnexus.core import ids
from songnexus.identity.sessions import SESSION_COOKIE, hash_token
from songnexus.identity.tokens import InvalidIdTokenError, VerifiedIdentity
from songnexus.jobs.purge import run_purge
from songnexus.service.app import build_state, create_app
from songnexus.service.deps import AppState
from songnexus.storage import migrate
from songnexus.storage import models as m
from songnexus.storage.db import make_engine, session_scope
from tests.catalog import fixtures as fx

ORIGIN = "http://localhost:5173"
ALICE = ids.artist_id("mb-alice")
BOB = ids.artist_id("mb-bob")
BAND = ids.artist_id("mb-band")
CAROL = ids.artist_id("mb-carol")


class FakeVerifier:
    def verify(self, id_token: str) -> VerifiedIdentity:
        if not id_token.startswith("uid:"):
            raise InvalidIdTokenError("bad token")
        return VerifiedIdentity(id_token.removeprefix("uid:"))


@pytest.fixture
def state(tmp_path: Path) -> AppState:
    snapshot = tmp_path / "snapshot.jsonl.gz"
    write_snapshot(fx.small_catalog(), snapshot)
    url = f"sqlite:///{tmp_path / 'app.db'}"
    engine = make_engine(url)
    migrate.upgrade(engine)
    ingest_snapshot(engine, snapshot)
    settings = Settings(database_url=url, log_json=False, read_model_refresh_s=3600)
    built = build_state(settings)
    built.verifier = FakeVerifier()
    return built


def new_client(state: AppState) -> TestClient:
    # https so the Secure session cookie is sent back.
    return TestClient(create_app(state.settings, state), base_url="https://testserver")


@pytest.fixture
def client(state: AppState) -> Iterator[TestClient]:
    with new_client(state) as test_client:
        yield test_client


def sign_in(client: TestClient, uid: str, *, age_confirmed: bool = True) -> dict[str, Any]:
    response = client.post(
        "/v1/sessions",
        json={"idToken": f"uid:{uid}", "ageConfirmed": age_confirmed},
        headers={"Origin": ORIGIN},
    )
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    client.headers.update({"Origin": ORIGIN, "X-CSRF-Token": body["csrfToken"]})
    return body


def reason(response: Any) -> str:
    return str(response.json()["error"]["details"][0]["reason"])


# ---------------------------------------------------------------------------
# Sign-in (AC-18.1)
# ---------------------------------------------------------------------------


def test_sign_in_sets_a_hardened_cookie_and_stores_only_a_hash(
    client: TestClient, state: AppState
) -> None:
    response = client.post(
        "/v1/sessions",
        json={"idToken": "uid:firebase-a", "ageConfirmed": True},
        headers={"Origin": ORIGIN},
    )
    assert response.status_code == 200
    assert response.json()["newUser"] is True
    cookie = response.headers["set-cookie"]
    assert cookie.startswith(f"{SESSION_COOKIE}=")
    for attribute in ("HttpOnly", "Secure", "SameSite=lax", "Path=/"):
        assert attribute.lower() in cookie.lower()
    assert "domain=" not in cookie.lower()
    assert response.headers["cache-control"] == "private, no-store"

    token = client.cookies[SESSION_COOKIE]
    with session_scope(state.engine) as session:
        stored = session.scalars(select(m.UserSession.token_hash)).all()
        firebase_uids = session.scalars(select(m.User.firebase_uid)).all()
    assert stored == [hash_token(token)]
    assert token not in stored
    assert firebase_uids == ["firebase-a"]

    me = client.get("/v1/users/me").json()
    assert me["name"] == response.json()["user"]


def test_sign_in_rejects_bad_tokens_wrong_origins_and_unconfirmed_age(client: TestClient) -> None:
    bad_token = client.post("/v1/sessions", json={"idToken": "forged"}, headers={"Origin": ORIGIN})
    assert (bad_token.status_code, reason(bad_token)) == (401, "ID_TOKEN_INVALID")

    cross_site = client.post(
        "/v1/sessions",
        json={"idToken": "uid:x", "ageConfirmed": True},
        headers={"Origin": "https://evil.example"},
    )
    assert (cross_site.status_code, reason(cross_site)) == (403, "ORIGIN_NOT_ALLOWED")

    no_origin = client.post("/v1/sessions", json={"idToken": "uid:x", "ageConfirmed": True})
    assert reason(no_origin) == "ORIGIN_NOT_ALLOWED"

    underage = client.post("/v1/sessions", json={"idToken": "uid:new"}, headers={"Origin": ORIGIN})
    assert (underage.status_code, reason(underage)) == (400, "AGE_CONFIRMATION_REQUIRED")
    assert SESSION_COOKIE not in client.cookies


def test_returning_users_do_not_need_to_reconfirm_age(client: TestClient) -> None:
    first = sign_in(client, "returning")
    client.delete("/v1/sessions/current")
    second = sign_in(client, "returning", age_confirmed=False)
    assert second["user"] == first["user"]
    assert second["newUser"] is False


def test_current_session_restores_the_csrf_token(client: TestClient) -> None:
    signed_in = sign_in(client, "reload")
    current = client.get("/v1/sessions/current").json()
    assert current == {
        "user": signed_in["user"],
        "csrfToken": signed_in["csrfToken"],
        "newUser": False,
    }


def test_anonymous_access_to_user_resources_is_unauthenticated(client: TestClient) -> None:
    for path in ("/v1/users/me", "/v1/users/me/preferences", "/v1/sessions/current"):
        response = client.get(path)
        assert (response.status_code, reason(response)) == (401, "SIGN_IN_REQUIRED")


# ---------------------------------------------------------------------------
# CSRF
# ---------------------------------------------------------------------------


def test_writes_require_the_csrf_token_and_an_allowed_origin(client: TestClient) -> None:
    sign_in(client, "csrf")
    body = {"artist": f"artists/{BOB}"}
    missing = client.post("/v1/users/me/blockedArtists", json=body, headers={"X-CSRF-Token": ""})
    assert (missing.status_code, reason(missing)) == (403, "CSRF_TOKEN_INVALID")
    wrong = client.post(
        "/v1/users/me/blockedArtists", json=body, headers={"X-CSRF-Token": "0" * 64}
    )
    assert reason(wrong) == "CSRF_TOKEN_INVALID"
    foreign = client.post(
        "/v1/users/me/blockedArtists", json=body, headers={"Origin": "https://evil.example"}
    )
    assert reason(foreign) == "ORIGIN_NOT_ALLOWED"
    assert client.get("/v1/users/me/blockedArtists").json()["totalSize"] == 0
    assert client.post("/v1/users/me/blockedArtists", json=body).status_code == 200


# ---------------------------------------------------------------------------
# Authorization (AC-18.2)
# ---------------------------------------------------------------------------


def test_users_cannot_touch_each_others_data(state: AppState) -> None:
    with new_client(state) as alice_client, new_client(state) as mallory:
        victim = sign_in(alice_client, "victim")["user"]
        assert (
            alice_client.post(
                "/v1/users/me/blockedArtists", json={"artist": f"artists/{BOB}"}
            ).status_code
            == 200
        )
        before = alice_client.get("/v1/users/me:export").json()
        sign_in(mallory, "mallory")

        attempts = [
            ("GET", f"/v1/{victim}", None),
            ("DELETE", f"/v1/{victim}", None),
            ("GET", f"/v1/{victim}:export", None),
            ("GET", f"/v1/{victim}/preferences", None),
            ("PATCH", f"/v1/{victim}/preferences", {"theme": "DARK"}),
            ("GET", f"/v1/{victim}/blockedArtists", None),
            ("POST", f"/v1/{victim}/blockedArtists", {"artist": f"artists/{CAROL}"}),
            ("DELETE", f"/v1/{victim}/blockedArtists/{BOB}", None),
            ("GET", f"/v1/{victim}/profile", None),
            ("PATCH", f"/v1/{victim}/profile", {"topArtists": [f"artists/{BOB}"]}),
            ("GET", "/v1/users/00000000-0000-0000-0000-000000000000/preferences", None),
        ]
        for method, path, body in attempts:
            response = mallory.request(method, path, json=body)
            assert (response.status_code, reason(response)) == (403, "NOT_YOUR_RESOURCE"), path

        assert alice_client.get("/v1/users/me:export").json() == before


# ---------------------------------------------------------------------------
# Preferences, ETags and update masks (AC-18.3)
# ---------------------------------------------------------------------------


def test_preferences_use_etags_and_update_masks(client: TestClient) -> None:
    sign_in(client, "prefs")
    initial = client.get("/v1/users/me/preferences").json()
    assert initial["theme"] == "SYSTEM"

    updated = client.patch(
        "/v1/users/me/preferences",
        params={"updateMask": "theme"},
        json={"theme": "DARK", "categories": ["LABELS"], "etag": initial["etag"]},
    ).json()
    assert updated["theme"] == "DARK"
    assert updated["categories"] == []  # not in the mask, so unchanged
    assert updated["etag"] != initial["etag"]

    stale = client.patch(
        "/v1/users/me/preferences", json={"theme": "LIGHT", "etag": initial["etag"]}
    )
    assert (stale.status_code, stale.json()["error"]["status"]) == (409, "ABORTED")
    assert client.get("/v1/users/me/preferences").json()["theme"] == "DARK"

    via_header = client.patch(
        "/v1/users/me/preferences",
        json={"theme": "LIGHT"},
        headers={"If-Match": initial["etag"]},
    )
    assert via_header.status_code == 409

    genre_id = client.get("/v1/genres").json()["genres"][0]["name"]
    with_genre = client.patch("/v1/users/me/preferences", json={"genres": [genre_id]}).json()
    assert with_genre["genres"] == [genre_id]
    unknown = client.patch(
        "/v1/users/me/preferences",
        json={"genres": ["genres/00000000-0000-0000-0000-000000000000"]},
    )
    assert reason(unknown) == "INVALID_ARGUMENT"
    bad_mask = client.patch("/v1/users/me/preferences", params={"updateMask": "email"}, json={})
    assert bad_mask.json()["error"]["details"][0]["metadata"]["field"] == "updateMask"


# ---------------------------------------------------------------------------
# Blocks (AC-17.1, AC-17.2)
# ---------------------------------------------------------------------------


def test_blocked_artist_disappears_from_every_list(client: TestClient) -> None:
    sign_in(client, "blocker")
    assert (
        client.post("/v1/users/me/blockedArtists", json={"artist": f"artists/{ALICE}"}).status_code
        == 200
    )
    blocked_name = f"artists/{ALICE}"

    def names(value: Any) -> set[str]:
        found: set[str] = set()
        if isinstance(value, dict):
            for key, item in value.items():
                if (
                    key in {"name", "artist"}
                    and isinstance(item, str)
                    and item.startswith("artists/")
                ):
                    found.add(item)
                found |= names(item)
        elif isinstance(value, list):
            for item in value:
                found |= names(item)
        return found

    others = [BOB, BAND, CAROL]
    for artist in others:
        connections = client.get(f"/v1/artists/{artist}/connections")
        assert connections.headers["cache-control"] == "private, no-store"
        assert blocked_name not in names(connections.json()["connections"])
        for kind in ("FEATURE", "PRODUCTION", "BAND", "CREDIT"):
            collabs = client.get(
                f"/v1/artists/{artist}/collaborations", params={"type": kind}
            ).json()
            assert blocked_name not in names(collabs["collaborations"])
    # Bob reaches The Band only through Alice: with Alice blocked there is no path.
    path = client.get(f"/v1/artists/{BOB}:findPath", params={"target": f"artists/{BAND}"}).json()
    assert path["outcome"] == "NOT_CONNECTED_WITHIN_LIMIT"
    compare = client.get(f"/v1/artists/{BOB}:compare", params={"other": f"artists/{CAROL}"}).json()
    assert blocked_name not in names(compare["mutualCollaborators"])
    assert blocked_name not in names(
        client.get("/v1/catalog:search", params={"query": "ali"}).json()
    )

    song = ids.recording_id(f"song|{ALICE}")
    assert blocked_name not in names(client.get(f"/v1/recordings/{song}").json()["credits"])

    # An exact search still finds the artist, flagged so it can be unblocked (AC-17.2).
    exact = client.get("/v1/catalog:search", params={"query": "Alice"}).json()["results"]
    assert exact[0]["name"] == blocked_name
    assert exact[0]["blocked"] is True
    # Explicitly chosen endpoints are allowed.
    assert (
        client.get(f"/v1/artists/{ALICE}:findPath", params={"target": f"artists/{BAND}"}).json()[
            "outcome"
        ]
        == "FOUND"
    )


def test_block_lifecycle(client: TestClient) -> None:
    sign_in(client, "lifecycle")
    created = client.post("/v1/users/me/blockedArtists", json={"artist": f"artists/{BOB}"})
    assert created.json()["artist"]["displayName"] == "Bob"
    again = client.post("/v1/users/me/blockedArtists", json={"artist": f"artists/{BOB}"})
    assert (again.status_code, reason(again)) == (409, "ALREADY_BLOCKED")
    listed = client.get("/v1/users/me/blockedArtists").json()
    assert [b["artist"]["name"] for b in listed["blockedArtists"]] == [f"artists/{BOB}"]
    assert client.delete(f"/v1/users/me/blockedArtists/{BOB}").status_code == 200
    gone = client.delete(f"/v1/users/me/blockedArtists/{BOB}")
    assert (gone.status_code, reason(gone)) == (404, "BLOCK_NOT_FOUND")
    unknown = client.post(
        "/v1/users/me/blockedArtists",
        json={"artist": "artists/00000000-0000-0000-0000-000000000000"},
    )
    assert reason(unknown) == "ARTIST_NOT_FOUND"


# ---------------------------------------------------------------------------
# Profile (AC-9.1)
# ---------------------------------------------------------------------------


def test_top_five_limit(client: TestClient) -> None:
    sign_in(client, "top5")
    four = [f"artists/{a}" for a in (ALICE, BOB, BAND, CAROL)]
    assert (
        client.patch("/v1/users/me/profile", json={"topArtists": four}).json()["topArtists"] == four
    )
    six = [*four, *(f"artists/{ids.artist_id(f'mb-x{i}')}" for i in range(2))]
    too_many = client.patch("/v1/users/me/profile", json={"topArtists": six})
    assert too_many.status_code == 400
    assert too_many.json()["error"]["details"][0]["metadata"]["field"] == "topArtists"
    assert client.get("/v1/users/me/profile").json()["topArtists"] == four


# ---------------------------------------------------------------------------
# Sign-out, revocation and deletion (AC-18.4)
# ---------------------------------------------------------------------------


def test_sign_out_everywhere_revokes_other_devices(state: AppState) -> None:
    with new_client(state) as laptop, new_client(state) as phone:
        sign_in(laptop, "multi")
        sign_in(phone, "multi")
        assert phone.post("/v1/sessions:revokeAll").status_code == 200
        assert laptop.get("/v1/users/me").status_code == 401
        assert phone.get("/v1/users/me").status_code == 401


def test_delete_account(client: TestClient, state: AppState) -> None:
    first = sign_in(client, "leaver")
    client.post("/v1/users/me/blockedArtists", json={"artist": f"artists/{BOB}"})
    client.patch("/v1/users/me/preferences", json={"theme": "DARK"})
    deleted = client.delete("/v1/users/me")
    assert deleted.status_code == 200
    assert client.get("/v1/users/me").status_code == 401

    with session_scope(state.engine) as session:
        for model in (m.Preferences, m.BlockedArtist, m.Profile, m.UserSession):
            assert session.scalars(select(model)).all() == []
        user = session.scalars(select(m.User)).one()
        assert user.firebase_uid is None
        assert user.deleted_at is not None

    again = sign_in(client, "leaver")
    assert again["newUser"] is True
    assert again["user"] != first["user"]

    later = datetime.now(UTC) + timedelta(days=30)
    assert run_purge(state.engine, now=later) == {"expiredSessions": 1, "deletedAccounts": 1}
    with session_scope(state.engine) as session:
        assert len(session.scalars(select(m.User)).all()) == 1


def test_export_contains_the_users_data(client: TestClient) -> None:
    signed_in = sign_in(client, "exporter")
    client.post("/v1/users/me/blockedArtists", json={"artist": f"artists/{BOB}"})
    response = client.get("/v1/users/me:export")
    assert "attachment" in response.headers["content-disposition"]
    exported = response.json()
    assert exported["user"]["name"] == signed_in["user"]
    assert exported["blockedArtists"] == [f"artists/{BOB}"]
    assert [e["action"] for e in exported["auditLog"]] == ["account.create", "block.create"]


def test_a_failed_commit_is_an_error_not_a_false_success(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """QA Q2: writes commit before the response is sent."""
    from songnexus.storage import user_repository

    def racing_add_block(session: Any, user_id: str, artist_id: str, now: datetime) -> bool:
        # Two tabs blocking the same artist at once: the second insert fails at commit.
        for _ in range(2):
            session.add(m.BlockedArtist(user_id=user_id, artist_id=artist_id, created_at=now))
        return True

    sign_in(client, "racer")
    monkeypatch.setattr(user_repository, "add_block", racing_add_block)
    no_raise = TestClient(client.app, base_url="https://testserver", raise_server_exceptions=False)
    no_raise.cookies = client.cookies
    no_raise.headers.update(client.headers)
    response = no_raise.post("/v1/users/me/blockedArtists", json={"artist": f"artists/{BOB}"})
    assert response.status_code == 500
    assert response.json()["error"]["status"] == "INTERNAL"


def test_signed_in_users_have_their_own_rate_limit(state: AppState) -> None:
    """QA Q6: users behind one address don't share a budget."""
    from songnexus.service.ratelimit import MethodClass, RateLimiter

    state.limiter = RateLimiter({MethodClass.READ: 2})
    with new_client(state) as first, new_client(state) as second:
        sign_in(first, "same-network-1")
        sign_in(second, "same-network-2")
        assert [first.get("/v1/genres").status_code for _ in range(3)] == [200, 200, 429]
        assert second.get("/v1/genres").status_code == 200
