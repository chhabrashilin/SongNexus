"""Linked accounts through the API (R2-6, ADR 0006), with every provider call mocked.

Covers: what is offered, token linking, the OAuth redirect flow (state bound to
the session, single use), sync into per-artist tallies, token refresh, revoked
links, unlinking, export, account deletion, and that tokens never leave.
"""

from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from songnexus.accounts.crypto import new_key
from songnexus.catalog.ingest import ingest_snapshot
from songnexus.catalog.snapshot import write_snapshot
from songnexus.config import Settings
from songnexus.core import ids
from songnexus.service.app import build_state, create_app
from songnexus.service.deps import AppState
from songnexus.service.sync_job import run_sync
from songnexus.storage import migrate
from songnexus.storage import models as m
from songnexus.storage.db import make_engine, session_scope
from tests.catalog import fixtures as fx
from tests.service.test_identity import ORIGIN, FakeVerifier, reason, sign_in

ALICE = ids.artist_id("mb-alice")
BOB = ids.artist_id("mb-bob")
APP = "http://127.0.0.1:5173"

Handler = Callable[[httpx.Request], httpx.Response]


class Providers:
    """A fake internet: routes outbound requests by host and path, and records them."""

    def __init__(self) -> None:
        self.routes: dict[str, Handler] = {}
        self.requests: list[httpx.Request] = []

    def on(self, url_prefix: str, handler: Handler | dict[str, Any], status: int = 200) -> None:
        if isinstance(handler, dict):
            body = handler
            self.routes[url_prefix] = lambda _r: httpx.Response(status, json=body)
        else:
            self.routes[url_prefix] = handler

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        url = str(request.url)
        for prefix in sorted(self.routes, key=len, reverse=True):
            if url.startswith(prefix):
                return self.routes[prefix](request)
        return httpx.Response(500, json={"unexpected": url})


def _settings(tmp_path: Path, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "database_url": f"sqlite:///{tmp_path / 'app.db'}",
        "log_json": False,
        "read_model_refresh_s": 3600,
        "token_keys": {"k1": new_key()},
        "token_key_id": "k1",
        "app_origin": APP,
        "spotify_client_id": "spotify-client",
        "google_client_id": "google-client",
        "google_client_secret": "google-secret",
        "lastfm_api_key": "lastfm-key",
        "lastfm_secret": "lastfm-secret",
        "listenbrainz_api_url": "https://lb.test",
        "lastfm_api_url": "https://lastfm.test/2.0/",
    }
    values.update(overrides)
    return Settings(**values)


def _state(tmp_path: Path, providers: Providers, **overrides: Any) -> AppState:
    snapshot = tmp_path / "snapshot.jsonl.gz"
    write_snapshot(fx.small_catalog(), snapshot)
    settings = _settings(tmp_path, **overrides)
    engine = make_engine(settings.database_url)
    migrate.upgrade(engine)
    ingest_snapshot(engine, snapshot)
    built = build_state(settings)
    built.verifier = FakeVerifier()
    built.outbound_http = lambda: httpx.Client(transport=httpx.MockTransport(providers))
    return built


@pytest.fixture
def providers() -> Providers:
    fake = Providers()
    fake.on("https://lb.test/1/validate-token", {"valid": True, "user_name": "lb-listener"})
    fake.on(
        "https://lb.test/1/user/lb-listener/listens",
        {
            "payload": {
                "listens": [
                    {
                        "listened_at": 1700000300,
                        "track_metadata": {
                            "artist_name": "Alice",
                            "mbid_mapping": {"artist_mbids": ["mb-alice"]},
                        },
                    },
                    {"listened_at": 1700000200, "track_metadata": {"artist_name": "Alice"}},
                    {"listened_at": 1700000100, "track_metadata": {"artist_name": "Bob"}},
                    {"listened_at": 1700000000, "track_metadata": {"artist_name": "Nobody Known"}},
                ]
            }
        },
    )
    return fake


@pytest.fixture
def state(tmp_path: Path, providers: Providers) -> AppState:
    return _state(tmp_path, providers)


@pytest.fixture
def client(state: AppState) -> Iterator[TestClient]:
    with TestClient(create_app(state.settings, state), base_url="https://testserver") as c:
        yield c


def _offers(client: TestClient) -> dict[str, dict[str, Any]]:
    body = client.get("/v1/users/me/linkedAccounts").json()
    return {offer["provider"]: offer for offer in body["providers"]}


def _link_listenbrainz(client: TestClient) -> dict[str, Any]:
    response = client.post(
        "/v1/users/me/linkedAccounts", json={"provider": "LISTENBRAINZ", "token": "lb-user-token"}
    )
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


# ---------------------------------------------------------------------------
# What is offered
# ---------------------------------------------------------------------------


def test_every_provider_is_listed_with_how_it_links(client: TestClient) -> None:
    sign_in(client, "listener")
    offers = _offers(client)
    assert set(offers) == {
        "LISTENBRAINZ",
        "LASTFM",
        "LIBREFM",
        "SPOTIFY",
        "DEEZER",
        "APPLE_MUSIC",
        "YOUTUBE_MUSIC",
    }
    assert offers["LISTENBRAINZ"]["method"] == "TOKEN"
    assert offers["SPOTIFY"]["method"] == "REDIRECT"
    assert offers["SPOTIFY"]["available"]
    assert offers["YOUTUBE_MUSIC"]["method"] == "REDIRECT"  # a Google client is configured
    assert offers["DEEZER"] == {
        "provider": "DEEZER",
        "method": "REDIRECT",
        "available": False,
        "unavailableReason": "PROVIDER_NOT_CONFIGURED",
        "linkedAccount": None,
    }


def test_youtube_music_falls_back_to_file_import_without_a_google_client(
    tmp_path: Path, providers: Providers
) -> None:
    state = _state(tmp_path, providers, google_client_id="", google_client_secret="")
    with TestClient(create_app(state.settings, state), base_url="https://testserver") as client:
        sign_in(client, "listener")
        offer = _offers(client)["YOUTUBE_MUSIC"]
        assert offer["method"] == "FILE"
        assert offer["available"]


def test_linked_accounts_need_a_signed_in_owner(client: TestClient) -> None:
    assert client.get("/v1/users/me/linkedAccounts").status_code == 401
    me = sign_in(client, "listener")["user"]
    assert client.get(f"/v1/{me}/linkedAccounts").status_code == 200
    assert client.get("/v1/users/someone-else/linkedAccounts").status_code in {403, 404}


def test_the_flag_switches_the_feature_off(tmp_path: Path, providers: Providers) -> None:
    state = _state(tmp_path, providers, flags={"linkedAccounts": False})
    with TestClient(create_app(state.settings, state), base_url="https://testserver") as client:
        sign_in(client, "listener")
        response = client.get("/v1/users/me/linkedAccounts")
        assert response.status_code == 503
        assert reason(response) == "FLAG_OFF"


# ---------------------------------------------------------------------------
# Token linking and sync (ListenBrainz)
# ---------------------------------------------------------------------------


def test_listenbrainz_links_with_a_validated_token_and_syncs_tallies(
    client: TestClient, state: AppState, providers: Providers
) -> None:
    sign_in(client, "listener")
    linked = _link_listenbrainz(client)
    assert linked["externalUser"] == "lb-listener"
    assert linked["status"] == "ACTIVE"
    assert "token" not in str(linked).lower().replace("unmatched", "")

    synced = client.post("/v1/users/me/linkedAccounts/listenbrainz:sync").json()
    assert (synced["synced"], synced["plays"], synced["artists"]) == (True, 4, 2)
    assert synced["unmatchedPlays"] == 1
    assert synced["linkedAccount"]["lastSyncTime"]

    listening = client.get("/v1/users/me/listening").json()
    assert [(a["artist"]["name"], a["plays"]) for a in listening["artists"]] == [
        (f"artists/{ALICE}", 2),
        (f"artists/{BOB}", 1),
    ]
    assert listening["artists"][0]["providers"] == ["LISTENBRAINZ"]
    assert listening["artists"][0]["lastPlayTime"] == "2023-11-14T22:18:20Z"

    with session_scope(state.engine) as session:
        account = session.scalars(select(m.LinkedAccount)).one()
        assert "lb-user-token" not in account.token_ciphertext  # encrypted at rest
        assert account.cursor == "1700000300"
        assert account.unmatched_plays == 1
    assert providers.requests[-1].url.params["min_ts"] == "0"  # the first sync reads everything


def test_sync_now_is_limited_to_once_a_minute(client: TestClient) -> None:
    sign_in(client, "listener")
    _link_listenbrainz(client)
    assert client.post("/v1/users/me/linkedAccounts/listenbrainz:sync").status_code == 200
    again = client.post("/v1/users/me/linkedAccounts/listenbrainz:sync")
    assert again.status_code == 429
    assert reason(again) == "SYNC_TOO_SOON"


def test_a_rejected_token_does_not_link(client: TestClient, providers: Providers) -> None:
    providers.on("https://lb.test/1/validate-token", {"valid": False})
    sign_in(client, "listener")
    response = client.post(
        "/v1/users/me/linkedAccounts", json={"provider": "LISTENBRAINZ", "token": "wrong"}
    )
    assert response.status_code == 400
    assert reason(response) == "LINK_REFUSED"
    assert _offers(client)["LISTENBRAINZ"]["linkedAccount"] is None


def test_writes_need_the_csrf_token(client: TestClient) -> None:
    sign_in(client, "listener")
    del client.headers["X-CSRF-Token"]
    response = client.post(
        "/v1/users/me/linkedAccounts", json={"provider": "LISTENBRAINZ", "token": "t"}
    )
    assert response.status_code == 403
    assert reason(response) == "CSRF_TOKEN_INVALID"


def test_a_revoked_link_asks_to_relink_and_relinking_keeps_history(
    client: TestClient, state: AppState, providers: Providers
) -> None:
    sign_in(client, "listener")
    _link_listenbrainz(client)
    listens = providers.routes["https://lb.test/1/user/lb-listener/listens"]
    providers.on("https://lb.test/1/user/lb-listener/listens", {}, status=401)
    synced = client.post("/v1/users/me/linkedAccounts/listenbrainz:sync").json()
    assert synced["synced"] is False
    assert synced["linkedAccount"]["status"] == "NEEDS_RELINK"

    providers.on("https://lb.test/1/user/lb-listener/listens", listens)
    assert _link_listenbrainz(client)["status"] == "ACTIVE"
    assert client.post("/v1/users/me/linkedAccounts/listenbrainz:sync").json()["plays"] == 4


def test_a_provider_outage_backs_off_and_keeps_the_link(
    client: TestClient, state: AppState, providers: Providers
) -> None:
    sign_in(client, "listener")
    _link_listenbrainz(client)
    providers.on("https://lb.test/1/user/lb-listener/listens", {}, status=503)
    synced = client.post("/v1/users/me/linkedAccounts/listenbrainz:sync").json()
    assert synced["synced"] is False
    assert synced["linkedAccount"]["status"] == "ACTIVE"
    with session_scope(state.engine) as session:
        account = session.scalars(select(m.LinkedAccount)).one()
        assert account.failures == 1
        assert account.next_sync_after is not None
        wait = account.next_sync_after.replace(tzinfo=UTC) - datetime.now(UTC)
        assert timedelta(minutes=25) < wait <= timedelta(minutes=30)  # 15 min doubled once


# ---------------------------------------------------------------------------
# Redirect linking (Spotify, YouTube Music, Last.fm)
# ---------------------------------------------------------------------------


def _start(client: TestClient, provider: str) -> dict[str, list[str]]:
    response = client.post("/v1/users/me/linkedAccounts:start", json={"provider": provider})
    assert response.status_code == 200, response.text
    url = urlparse(response.json()["authorizationUrl"])
    query = parse_qs(url.query)
    query["_host"] = [url.netloc]
    return query


def _spotify(providers: Providers) -> None:
    def token(request: httpx.Request) -> httpx.Response:
        form = parse_qs(request.content.decode())
        if form["grant_type"] == ["refresh_token"]:
            return httpx.Response(200, json={"access_token": "access-2", "expires_in": 3600})
        assert form["code"] == ["the-code"]
        assert form["code_verifier"][0]
        return httpx.Response(
            200,
            json={"access_token": "access-1", "refresh_token": "refresh-1", "expires_in": 3600},
        )

    providers.on("https://accounts.spotify.com/api/token", token)
    providers.on("https://api.spotify.com/v1/me", {"id": "spotify-listener"})
    providers.on(
        "https://api.spotify.com/v1/me/player/recently-played",
        {
            "items": [
                {
                    "played_at": "2023-11-14T22:15:00.000Z",
                    "track": {"artists": [{"name": "Alice"}, {"name": "Bob"}]},
                }
            ]
        },
    )


def test_spotify_links_with_pkce_and_state_then_syncs(
    client: TestClient, state: AppState, providers: Providers
) -> None:
    _spotify(providers)
    sign_in(client, "listener")
    query = _start(client, "SPOTIFY")
    assert query["_host"] == ["accounts.spotify.com"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["code_challenge"][0]
    assert query["redirect_uri"] == [f"{APP}/v1/oauth/spotify/callback"]
    assert query["scope"] == ["user-read-recently-played"]

    callback = client.get(
        "/v1/oauth/spotify/callback",
        params={"state": query["state"][0], "code": "the-code"},
        follow_redirects=False,
    )
    assert callback.status_code == 303
    assert callback.headers["location"] == f"{APP}/you?linked=SPOTIFY"
    assert _offers(client)["SPOTIFY"]["linkedAccount"]["externalUser"] == "spotify-listener"

    synced = client.post("/v1/users/me/linkedAccounts/spotify:sync").json()
    assert (synced["plays"], synced["artists"]) == (2, 2)
    sent = [r for r in providers.requests if "recently-played" in str(r.url)][-1]
    assert sent.headers["Authorization"] == "Bearer access-1"

    # The state is single use.
    replay = client.get(
        "/v1/oauth/spotify/callback",
        params={"state": query["state"][0], "code": "the-code"},
        follow_redirects=False,
    )
    assert replay.headers["location"] == f"{APP}/you?linkError=LINK_STATE_INVALID"


def test_an_expired_spotify_token_is_refreshed_before_sync(
    client: TestClient, state: AppState, providers: Providers
) -> None:
    _spotify(providers)
    sign_in(client, "listener")
    query = _start(client, "SPOTIFY")
    client.get(
        "/v1/oauth/spotify/callback",
        params={"state": query["state"][0], "code": "the-code"},
        follow_redirects=False,
    )
    with session_scope(state.engine) as session:
        account = session.scalars(select(m.LinkedAccount)).one()
        account.token_expires_at = datetime.now(UTC) - timedelta(minutes=1)
    assert client.post("/v1/users/me/linkedAccounts/spotify:sync").json()["synced"] is True
    sent = [r for r in providers.requests if "recently-played" in str(r.url)][-1]
    assert sent.headers["Authorization"] == "Bearer access-2"


def test_a_link_started_in_one_session_cannot_be_finished_in_another(
    state: AppState, providers: Providers
) -> None:
    _spotify(providers)
    app = create_app(state.settings, state)
    with (
        TestClient(app, base_url="https://testserver") as victim,
        TestClient(app, base_url="https://testserver") as attacker,
    ):
        sign_in(attacker, "attacker")
        attacker_state = _start(attacker, "SPOTIFY")["state"][0]
        # The attacker gets the victim to open the callback with the attacker's state.
        sign_in(victim, "victim")
        response = victim.get(
            "/v1/oauth/spotify/callback",
            params={"state": attacker_state, "code": "the-code"},
            follow_redirects=False,
        )
        assert response.headers["location"].endswith("linkError=LINK_STATE_INVALID")
        assert _offers(victim)["SPOTIFY"]["linkedAccount"] is None
        assert _offers(attacker)["SPOTIFY"]["linkedAccount"] is None


def test_declining_on_the_provider_returns_to_the_app(client: TestClient) -> None:
    sign_in(client, "listener")
    response = client.get(
        "/v1/oauth/spotify/callback", params={"error": "access_denied"}, follow_redirects=False
    )
    assert response.headers["location"] == f"{APP}/you?linkError=LINK_DECLINED"


def test_youtube_music_links_through_google_and_counts_liked_songs_once(
    client: TestClient, providers: Providers
) -> None:
    providers.on(
        "https://oauth2.googleapis.com/token",
        {"access_token": "yt-access", "refresh_token": "yt-refresh", "expires_in": 3600},
    )
    providers.on(
        "https://www.googleapis.com/youtube/v3/channels",
        {"items": [{"snippet": {"title": "My Channel"}}]},
    )
    providers.on(
        "https://www.googleapis.com/youtube/v3/videos",
        {
            "items": [
                {
                    "id": "v3",
                    "snippet": {"categoryId": "10", "channelTitle": "Alice - Topic", "title": "S"},
                },
                {
                    "id": "v2",
                    "snippet": {
                        "categoryId": "10",
                        "channelTitle": "SomeLabelVEVO",
                        "title": "Bob - A Song (Official Video)",
                    },
                },
                {
                    "id": "v1",
                    "snippet": {"categoryId": "22", "channelTitle": "Alice", "title": "A vlog"},
                },
            ]
        },
    )
    sign_in(client, "listener")
    query = _start(client, "YOUTUBE_MUSIC")
    assert query["_host"] == ["accounts.google.com"]
    assert query["scope"] == ["https://www.googleapis.com/auth/youtube.readonly"]
    assert query["access_type"] == ["offline"]
    callback = client.get(
        "/v1/oauth/youtube_music/callback",
        params={"state": query["state"][0], "code": "google-code"},
        follow_redirects=False,
    )
    assert callback.headers["location"] == f"{APP}/you?linked=YOUTUBE_MUSIC"
    first = client.post("/v1/users/me/linkedAccounts/youtube_music:sync").json()
    assert (first["plays"], first["artists"]) == (2, 2)  # the vlog is not music


def test_lastfm_links_with_a_signed_session_exchange(
    client: TestClient, providers: Providers
) -> None:
    def lastfm(request: httpx.Request) -> httpx.Response:
        params = request.url.params
        if params["method"] == "auth.getSession":
            assert params["token"] == "lastfm-token"
            assert len(params["api_sig"]) == 32
            return httpx.Response(200, json={"session": {"name": "fm-listener", "key": "sk"}})
        assert params["user"] == "fm-listener"
        return httpx.Response(
            200,
            json={
                "recenttracks": {
                    "track": [{"artist": {"#text": "Alice"}, "date": {"uts": "1700000000"}}],
                    "@attr": {"totalPages": "1"},
                }
            },
        )

    providers.on("https://lastfm.test/2.0/", lastfm)
    sign_in(client, "listener")
    query = _start(client, "LASTFM")
    callback_url = urlparse(query["cb"][0])
    state_value = parse_qs(callback_url.query)["state"][0]
    client.get(
        "/v1/oauth/lastfm/callback",
        params={"state": state_value, "token": "lastfm-token"},
        follow_redirects=False,
    )
    assert _offers(client)["LASTFM"]["linkedAccount"]["externalUser"] == "fm-listener"
    assert client.post("/v1/users/me/linkedAccounts/lastfm:sync").json()["plays"] == 1


# ---------------------------------------------------------------------------
# Unlink, export, deletion, the scheduled job
# ---------------------------------------------------------------------------


def test_unlinking_deletes_the_token_and_every_tally(client: TestClient, state: AppState) -> None:
    sign_in(client, "listener")
    _link_listenbrainz(client)
    client.post("/v1/users/me/linkedAccounts/listenbrainz:sync")
    assert client.delete("/v1/users/me/linkedAccounts/listenbrainz").status_code == 200
    assert client.get("/v1/users/me/listening").json()["artists"] == []
    with session_scope(state.engine) as session:
        assert session.scalars(select(m.LinkedAccount)).all() == []
        assert session.scalars(select(m.ListeningTally)).all() == []
    missing = client.delete("/v1/users/me/linkedAccounts/listenbrainz")
    assert missing.status_code == 404
    assert reason(missing) == "LINK_NOT_FOUND"


def test_export_includes_links_and_tallies_but_never_tokens(client: TestClient) -> None:
    sign_in(client, "listener")
    _link_listenbrainz(client)
    client.post("/v1/users/me/linkedAccounts/listenbrainz:sync")
    response = client.get("/v1/users/me:export")
    export = response.json()
    assert export["linkedAccounts"][0]["provider"] == "LISTENBRAINZ"
    assert export["linkedAccounts"][0]["externalUser"] == "lb-listener"
    assert {row["artist"]: row["plays"] for row in export["listening"]} == {
        f"artists/{ALICE}": 2,
        f"artists/{BOB}": 1,
    }
    assert "lb-user-token" not in response.text
    assert "ciphertext" not in response.text.lower()


def test_deleting_the_account_removes_links_and_tallies(
    client: TestClient, state: AppState
) -> None:
    sign_in(client, "listener")
    _link_listenbrainz(client)
    client.post("/v1/users/me/linkedAccounts/listenbrainz:sync")
    assert client.delete("/v1/users/me").status_code == 200
    with session_scope(state.engine) as session:
        assert session.scalars(select(m.LinkedAccount)).all() == []
        assert session.scalars(select(m.ListeningTally)).all() == []


def test_the_scheduled_job_syncs_due_accounts_and_skips_the_rest(
    client: TestClient, state: AppState, providers: Providers
) -> None:
    sign_in(client, "listener")
    _link_listenbrainz(client)
    model = state.holder.current()
    with httpx.Client(transport=httpx.MockTransport(providers)) as http:
        first = run_sync(state.engine, state.settings, model, http)
        assert (first["accounts"], first["plays"]) == (1, 4)
        again = run_sync(state.engine, state.settings, model, http)
        assert again["accounts"] == 0  # not due for another 15 minutes
        later = datetime.now(UTC) + timedelta(minutes=16)
        assert run_sync(state.engine, state.settings, model, http, now=later)["accounts"] == 1


def test_blocked_artists_are_hidden_from_listening(client: TestClient) -> None:
    sign_in(client, "listener")
    _link_listenbrainz(client)
    client.post("/v1/users/me/linkedAccounts/listenbrainz:sync")
    client.post("/v1/users/me/blockedArtists", json={"artist": f"artists/{BOB}"})
    names = [a["artist"]["name"] for a in client.get("/v1/users/me/listening").json()["artists"]]
    assert names == [f"artists/{ALICE}"]


def test_local_sign_in_exists_only_in_development_without_firebase(
    client: TestClient, tmp_path: Path, providers: Providers
) -> None:
    assert client.get("/v1/config").json()["flags"]["localSignIn"] is True
    response = client.post(
        "/v1/sessions:local",
        json={"listener": "demo-1", "ageConfirmed": True},
        headers={"Origin": ORIGIN},
    )
    assert response.status_code == 200
    assert response.json()["newUser"] is True

    (tmp_path / "with-firebase").mkdir()
    configured = _state(tmp_path / "with-firebase", providers, firebase_project_id="a-project")
    with TestClient(create_app(configured.settings, configured)) as other:
        assert other.get("/v1/config").json()["flags"]["localSignIn"] is False
        refused = other.post(
            "/v1/sessions:local", json={"ageConfirmed": True}, headers={"Origin": ORIGIN}
        )
        assert refused.status_code == 404
