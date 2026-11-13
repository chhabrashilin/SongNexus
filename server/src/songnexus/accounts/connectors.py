"""One interface for every listening service (ADR 0006, decision 1).

``fetch(http, credentials, cursor)`` returns the plays since ``cursor`` and the
next cursor. Connectors never write responses to disk (a listener's history is
not catalog data), never log tokens, and raise ``RevokedError`` when the service
says the link no longer works, so the account can be marked for relinking.

Plays carry only what aggregation needs: the artist (name, and MusicBrainz ID
when the service gives one) and when it was played.
"""

from __future__ import annotations

import enum
import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

import httpx

log = logging.getLogger(__name__)

HTTP_OK = 200
HTTP_UNAUTHORIZED = 401
HTTP_FORBIDDEN = 403
_REVOKED = frozenset({HTTP_UNAUTHORIZED, HTTP_FORBIDDEN})


class Provider(enum.StrEnum):
    """A listening service."""

    LISTENBRAINZ = "LISTENBRAINZ"
    LASTFM = "LASTFM"
    LIBREFM = "LIBREFM"
    SPOTIFY = "SPOTIFY"
    DEEZER = "DEEZER"
    APPLE_MUSIC = "APPLE_MUSIC"
    YOUTUBE_MUSIC = "YOUTUBE_MUSIC"


@dataclass(frozen=True)
class Play:
    """One play: the artist and when (Unix seconds; None when the service gives no time)."""

    artist_name: str
    artist_mbid: str | None = None
    played_at: int | None = None


@dataclass(frozen=True)
class Credentials:
    """What a connector needs to read one listener's history (decrypted, in memory only)."""

    external_user: str
    access_token: str = ""
    extra: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Page:
    """Plays since the cursor, the next cursor, and whether more are waiting."""

    plays: tuple[Play, ...]
    cursor: str | None
    more: bool = False


class ConnectorError(RuntimeError):
    """The service failed in a way a later sync may not (5xx, timeouts, rate limits)."""


class RevokedError(ConnectorError):
    """The service rejected the credentials: the listener has to link again."""


class Connector(Protocol):
    """A listening service's history, read incrementally."""

    provider: Provider

    def fetch(self, http: httpx.Client, credentials: Credentials, cursor: str | None) -> Page:
        """Returns the plays after ``cursor`` (all available history when None)."""
        ...


def _get(http: httpx.Client, url: str, **kwargs: Any) -> Any:
    try:
        response = http.get(url, **kwargs)
    except httpx.HTTPError as exc:
        raise ConnectorError(f"GET {httpx.URL(url).host}: {type(exc).__name__}") from exc
    if response.status_code in _REVOKED:
        raise RevokedError(f"{httpx.URL(url).host} rejected the credentials")
    if response.status_code != HTTP_OK:
        raise ConnectorError(f"{httpx.URL(url).host} -> {response.status_code}")
    return response.json()


def _int_cursor(cursor: str | None) -> int:
    return int(cursor) if cursor and cursor.isdigit() else 0


class ListenBrainzConnector:
    """``GET /1/user/{user}/listens`` with the user's token; cursor = last ``listened_at``."""

    provider = Provider.LISTENBRAINZ
    page_size = 1000

    def __init__(self, api_url: str = "https://api.listenbrainz.org") -> None:
        self.api_url = api_url.rstrip("/")

    def fetch(self, http: httpx.Client, credentials: Credentials, cursor: str | None) -> Page:
        """Returns the plays after ``cursor``."""
        since = _int_cursor(cursor)
        body = _get(
            http,
            f"{self.api_url}/1/user/{credentials.external_user}/listens",
            params={"min_ts": since, "count": self.page_size},
            headers={"Authorization": f"Token {credentials.access_token}"},
        )
        listens = body.get("payload", {}).get("listens", [])
        plays = []
        for listen in listens:
            meta = listen.get("track_metadata", {})
            mbids = (
                (meta.get("mbid_mapping") or {}).get("artist_mbids")
                or (meta.get("additional_info") or {}).get("artist_mbids")
                or []
            )
            name = meta.get("artist_name")
            if name:
                plays.append(Play(name, mbids[0] if mbids else None, listen.get("listened_at")))
        newest = max((p.played_at or 0 for p in plays), default=since)
        return Page(tuple(plays), str(newest), more=len(listens) >= self.page_size)


class LastFmConnector:
    """``user.getRecentTracks`` on Last.fm or Libre.fm (same API); cursor = last ``uts``."""

    page_size = 200
    max_pages = 10  # per sync; the rest waits for the next run

    def __init__(self, provider: Provider, api_url: str) -> None:
        self.provider = provider
        self.api_url = api_url

    def fetch(self, http: httpx.Client, credentials: Credentials, cursor: str | None) -> Page:
        """Returns the plays after ``cursor``."""
        since = _int_cursor(cursor)
        plays: list[Play] = []
        total_pages = 1
        page = 1
        while page <= min(total_pages, self.max_pages):
            body = _get(
                http,
                self.api_url,
                params={
                    "method": "user.getrecenttracks",
                    "user": credentials.external_user,
                    "api_key": credentials.extra.get("api_key", ""),
                    "from": since + 1,
                    "limit": self.page_size,
                    "page": page,
                    "format": "json",
                },
            )
            if "error" in body:
                # 4 (auth), 9 (session), 26 (suspended key): the link no longer works.
                if body.get("error") in {4, 9, 26}:
                    raise RevokedError(f"{self.provider} rejected the credentials")
                raise ConnectorError(f"{self.provider} error {body.get('error')}")
            tracks = body.get("recenttracks", {})
            total_pages = int(tracks.get("@attr", {}).get("totalPages", 1) or 1)
            for track in tracks.get("track", []):
                uts = (track.get("date") or {}).get("uts")
                artist = track.get("artist") or {}
                name = artist.get("#text") or artist.get("name")
                if uts and name:  # "now playing" has no date: counted once it ends
                    plays.append(Play(name, artist.get("mbid") or None, int(uts)))
            page += 1
        newest = max((p.played_at or 0 for p in plays), default=since)
        return Page(tuple(plays), str(newest), more=total_pages > self.max_pages)


class SpotifyConnector:
    """``me/player/recently-played`` (the last 50 plays); cursor = last ``played_at`` in ms."""

    provider = Provider.SPOTIFY

    def __init__(self, api_url: str = "https://api.spotify.com/v1") -> None:
        self.api_url = api_url.rstrip("/")

    def fetch(self, http: httpx.Client, credentials: Credentials, cursor: str | None) -> Page:
        """Returns the plays after ``cursor``."""
        since = _int_cursor(cursor)
        params: dict[str, int] = {"limit": 50}
        if since:
            params["after"] = since
        body = _get(
            http,
            f"{self.api_url}/me/player/recently-played",
            params=params,
            headers={"Authorization": f"Bearer {credentials.access_token}"},
        )
        plays = []
        newest = since
        for item in body.get("items", []):
            played = datetime.fromisoformat(item["played_at"].replace("Z", "+00:00"))
            millis = int(played.timestamp() * 1000)
            newest = max(newest, millis)
            for artist in item.get("track", {}).get("artists", []):
                if artist.get("name"):
                    plays.append(Play(artist["name"], None, millis // 1000))
        return Page(tuple(plays), str(newest))


class DeezerConnector:
    """``user/me/history``; the API has no "since", so older plays are skipped by cursor."""

    provider = Provider.DEEZER

    def __init__(self, api_url: str = "https://api.deezer.com") -> None:
        self.api_url = api_url.rstrip("/")

    def fetch(self, http: httpx.Client, credentials: Credentials, cursor: str | None) -> Page:
        """Returns the plays after ``cursor``."""
        since = _int_cursor(cursor)
        body = _get(
            http,
            f"{self.api_url}/user/me/history",
            params={"access_token": credentials.access_token, "limit": 100},
        )
        if "error" in body:
            raise RevokedError("deezer rejected the credentials")
        plays = [
            Play(row["artist"]["name"], None, int(row["timestamp"]))
            for row in body.get("data", [])
            if row.get("timestamp") and int(row["timestamp"]) > since and row.get("artist")
        ]
        newest = max((p.played_at or 0 for p in plays), default=since)
        return Page(tuple(plays), str(newest))


class AppleMusicConnector:
    """``me/recent/played/tracks``, which has no play times and lists a repeated song once.

    The cursor is therefore the set of track IDs seen last time; only new IDs count as plays.
    """

    provider = Provider.APPLE_MUSIC

    def __init__(self, api_url: str = "https://api.music.apple.com/v1") -> None:
        self.api_url = api_url.rstrip("/")

    def fetch(self, http: httpx.Client, credentials: Credentials, cursor: str | None) -> Page:
        """Returns the plays after ``cursor``."""
        seen = set(cursor.split(",")) if cursor else set()
        body = _get(
            http,
            f"{self.api_url}/me/recent/played/tracks",
            params={"limit": 30, "types": "songs"},
            headers={
                "Authorization": f"Bearer {credentials.extra.get('developer_token', '')}",
                "Music-User-Token": credentials.access_token,
            },
        )
        items = body.get("data", [])
        plays = [
            Play(item["attributes"]["artistName"])
            for item in items
            if item.get("id") not in seen and item.get("attributes", {}).get("artistName")
        ]
        return Page(tuple(plays), ",".join(sorted(i["id"] for i in items if i.get("id"))))


YOUTUBE_MUSIC_CATEGORY = "10"
_TOPIC_SUFFIX = " - Topic"


def youtube_artist(channel_title: str, video_title: str) -> str:
    """The artist of a liked music video.

    YouTube Music's own uploads live on "<Artist> - Topic" channels. Elsewhere the
    usual title is "Artist - Song"; failing both, the channel name is the best guess.
    The import matcher then accepts only confident catalog matches.
    """
    if channel_title.endswith(_TOPIC_SUFFIX):
        return channel_title.removesuffix(_TOPIC_SUFFIX).strip()
    head, separator, _rest = video_title.partition(" - ")
    if separator and head.strip():
        return head.strip()
    return channel_title.strip()


class YouTubeConnector:
    """Liked music from the YouTube Data API (``videos?myRating=like``, music category).

    YouTube has no listening-history API, but songs liked in YouTube Music are likes
    on YouTube, newest first. Each liked song counts once. Likes carry no time, so the
    cursor is the newest video IDs seen last time: reading stops at the first of them.
    """

    provider = Provider.YOUTUBE_MUSIC
    page_size = 50
    max_pages = 20  # 1,000 likes per sync, one quota unit per page
    cursor_ids = 25

    def __init__(self, api_url: str = "https://www.googleapis.com/youtube/v3") -> None:
        self.api_url = api_url.rstrip("/")

    def fetch(self, http: httpx.Client, credentials: Credentials, cursor: str | None) -> Page:
        """Returns the songs liked since ``cursor``."""
        seen = set(cursor.split(",")) if cursor else set()
        plays: list[Play] = []
        newest: list[str] = []
        token = ""
        for _ in range(self.max_pages):
            params: dict[str, str | int] = {
                "part": "snippet",
                "myRating": "like",
                "maxResults": self.page_size,
            }
            if token:
                params["pageToken"] = token
            body = _get(
                http,
                f"{self.api_url}/videos",
                params=params,
                headers={"Authorization": f"Bearer {credentials.access_token}"},
            )
            caught_up = False
            for item in body.get("items", []):
                video_id = item.get("id")
                if video_id in seen:
                    caught_up = True
                    break
                if video_id and len(newest) < self.cursor_ids:
                    newest.append(video_id)
                snippet = item.get("snippet") or {}
                if snippet.get("categoryId") != YOUTUBE_MUSIC_CATEGORY:
                    continue
                name = youtube_artist(snippet.get("channelTitle", ""), snippet.get("title", ""))
                if name:
                    plays.append(Play(name))
            token = body.get("nextPageToken", "")
            if caught_up or not token:
                break
        # Keep earlier IDs too, so unliking the newest song does not replay the whole list.
        kept = newest + [v for v in (cursor.split(",") if cursor else []) if v not in newest]
        return Page(tuple(plays), ",".join(kept[: self.cursor_ids]) or None)


class YouTubeMusicFirstPartyAdapter:
    """The seam for YouTube Music's own history (no public API exists).

    A YouTube Music integration implements ``fetch`` against the internal history
    service with the same contract: plays after the cursor, oldest first or in any
    order, artist names and (when known) MusicBrainz or catalog IDs. Until then,
    listeners import Google Takeout files on the device (``web/src/importers``).
    """

    provider = Provider.YOUTUBE_MUSIC

    def fetch(self, http: httpx.Client, credentials: Credentials, cursor: str | None) -> Page:
        """Returns the plays after ``cursor``."""
        raise NotImplementedError("YouTube Music history is first-party; see the integration guide")
