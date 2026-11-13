"""Connector contracts against recorded-style responses (no network), and token encryption."""

import base64
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from songnexus.accounts import connectors as c
from songnexus.accounts.crypto import TokenCipher, TokenCipherError, new_key

CREDS = c.Credentials(external_user="listener", access_token="secret-token", extra={"api_key": "k"})


def _http(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _json(body: Any, status: int = 200) -> Callable[[httpx.Request], httpx.Response]:
    return lambda _r: httpx.Response(status, json=body)


def test_listenbrainz_reads_listens_since_the_cursor_with_the_token() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "payload": {
                    "listens": [
                        {
                            "listened_at": 1700000100,
                            "track_metadata": {
                                "artist_name": "Kendrick Lamar",
                                "mbid_mapping": {"artist_mbids": ["mb-k"]},
                            },
                        },
                        {"listened_at": 1700000050, "track_metadata": {"artist_name": "SZA"}},
                    ]
                }
            },
        )

    page = c.ListenBrainzConnector("https://lb.test").fetch(_http(handler), CREDS, "1700000000")
    assert seen[0].url.params["min_ts"] == "1700000000"
    assert seen[0].headers["Authorization"] == "Token secret-token"
    assert page.plays == (
        c.Play("Kendrick Lamar", "mb-k", 1700000100),
        c.Play("SZA", None, 1700000050),
    )
    assert page.cursor == "1700000100"


def test_lastfm_skips_now_playing_and_pages() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params["page"])
        tracks = [
            {"artist": {"#text": f"Artist {page}", "mbid": ""}, "date": {"uts": str(100 + page)}}
        ]
        if page == 1:
            tracks.insert(0, {"artist": {"#text": "Now"}, "@attr": {"nowplaying": "true"}})
        return httpx.Response(
            200, json={"recenttracks": {"track": tracks, "@attr": {"totalPages": "2"}}}
        )

    page = c.LastFmConnector(c.Provider.LASTFM, "https://lastfm.test/2.0/").fetch(
        _http(handler), CREDS, "50"
    )
    assert [p.artist_name for p in page.plays] == ["Artist 1", "Artist 2"]
    assert page.cursor == "102"
    assert not page.more


def test_lastfm_auth_errors_mean_relink() -> None:
    with pytest.raises(c.RevokedError):
        c.LastFmConnector(c.Provider.LIBREFM, "https://libre.test/2.0/").fetch(
            _http(_json({"error": 9, "message": "Invalid session key"})), CREDS, None
        )


def test_spotify_uses_after_and_bearer_tokens() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer secret-token"
        assert request.url.params["after"] == "1700000000000"
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "played_at": "2023-11-14T22:15:00.000Z",
                        "track": {"artists": [{"name": "Daft Punk"}, {"name": "Pharrell"}]},
                    }
                ]
            },
        )

    page = c.SpotifyConnector("https://spotify.test/v1").fetch(
        _http(handler), CREDS, "1700000000000"
    )
    assert [p.artist_name for p in page.plays] == ["Daft Punk", "Pharrell"]
    assert int(page.cursor or 0) > 1700000000000


def test_a_rejected_token_raises_revoked_and_5xx_is_retryable() -> None:
    with pytest.raises(c.RevokedError):
        c.SpotifyConnector().fetch(_http(_json({}, 401)), CREDS, None)
    with pytest.raises(c.ConnectorError) as error:
        c.SpotifyConnector().fetch(_http(_json({}, 503)), CREDS, None)
    assert not isinstance(error.value, c.RevokedError)
    assert "secret-token" not in str(error.value)


def test_deezer_filters_by_cursor_because_its_api_cannot() -> None:
    body = {
        "data": [
            {"timestamp": 200, "artist": {"name": "New"}},
            {"timestamp": 90, "artist": {"name": "Old"}},
        ]
    }
    page = c.DeezerConnector("https://deezer.test").fetch(_http(_json(body)), CREDS, "100")
    assert [p.artist_name for p in page.plays] == ["New"]
    assert page.cursor == "200"


def test_apple_music_counts_only_tracks_not_seen_last_time() -> None:
    body = {
        "data": [
            {"id": "t1", "attributes": {"artistName": "SZA"}},
            {"id": "t2", "attributes": {"artistName": "Drake"}},
        ]
    }
    first = c.AppleMusicConnector("https://apple.test/v1").fetch(_http(_json(body)), CREDS, None)
    again = c.AppleMusicConnector("https://apple.test/v1").fetch(
        _http(_json(body)), CREDS, first.cursor
    )
    assert len(first.plays) == 2
    assert again.plays == ()


def test_youtube_music_is_a_first_party_seam() -> None:
    with pytest.raises(NotImplementedError, match="first-party"):
        c.YouTubeMusicFirstPartyAdapter().fetch(_http(_json({})), CREDS, None)


def test_tokens_are_encrypted_bound_to_their_account_and_rotatable() -> None:
    old = TokenCipher.from_config({"k1": new_key()}, "k1")
    sealed = old.encrypt("refresh-token", context="users/u1/SPOTIFY")
    assert "refresh-token" not in sealed
    assert old.decrypt(sealed, context="users/u1/SPOTIFY") == "refresh-token"
    with pytest.raises(TokenCipherError):
        old.decrypt(sealed, context="users/u2/SPOTIFY")  # copied onto another account
    rotated = TokenCipher.from_config({"k1": _b64(old.keys["k1"]), "k2": new_key()}, "k2")
    assert rotated.decrypt(sealed, context="users/u1/SPOTIFY") == "refresh-token"
    assert rotated.needs_rotation(sealed)
    with pytest.raises(TokenCipherError):
        TokenCipher.from_config({"k1": "c2hvcnQ="}, "k1")  # not 32 bytes


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode()


def test_youtube_reads_liked_music_and_stops_at_what_it_saw_last_time() -> None:
    def video(video_id: str, channel: str, title: str = "Song", category: str = "10") -> Any:
        return {
            "id": video_id,
            "snippet": {"categoryId": category, "channelTitle": channel, "title": title},
        }

    pages = {
        "": {
            "items": [video("v5", "SZA - Topic"), video("v4", "Gaming", "Let's play", "20")],
            "nextPageToken": "p2",
        },
        "p2": {"items": [video("v3", "LabelVEVO", "Drake - Song"), video("v2", "Old - Topic")]},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer secret-token"
        assert request.url.params["myRating"] == "like"
        return httpx.Response(200, json=pages[request.url.params.get("pageToken", "")])

    connector = c.YouTubeConnector("https://yt.test/v3")
    first = connector.fetch(_http(handler), CREDS, "v2,v1")
    assert first.plays == (c.Play("SZA"), c.Play("Drake"))  # v2 was seen; v4 is not music
    assert (first.cursor or "").split(",")[:3] == ["v5", "v4", "v3"]
    assert connector.fetch(_http(handler), CREDS, first.cursor).plays == ()


def test_youtube_artist_prefers_topic_channels_then_the_title() -> None:
    assert c.youtube_artist("Kendrick Lamar - Topic", "HUMBLE.") == "Kendrick Lamar"
    assert c.youtube_artist("KendrickLamarVEVO", "Kendrick Lamar - HUMBLE.") == "Kendrick Lamar"
    assert c.youtube_artist("Some Channel", "A live session") == "Some Channel"
