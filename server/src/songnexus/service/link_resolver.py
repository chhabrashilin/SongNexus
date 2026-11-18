"""ResolveLink: turns a link from another music app into a SongNexus artist or song.

The order is cheapest and surest first:

1. **Our catalog.** MusicBrainz stores the streaming pages of many artists; the
   read model indexes them by link key, so most artist links need no network.
2. **MusicBrainz's URL index.** ``/ws/2/url?resource=`` maps a streaming page to
   a MusicBrainz ID, and so to our artist ID (CC0, the catalog's own source).
3. **The service's public metadata.** Deezer's API and Apple's lookup API return
   title, artists and (Deezer) the ISRC, which MusicBrainz maps to recordings.
   Spotify, YouTube, SoundCloud and Tidal publish oEmbed: a title and, for
   videos, the channel. Spotify's Web API is used only when a client secret is
   configured.
4. **Names.** Whatever names those give are matched with the import matcher,
   which never auto-picks between namesakes: ambiguity comes back as candidates.

Privacy: the link is read, never stored. Only its identifying part is sent on
(tracking parameters are stripped by ``core.links``), with the project's
User-Agent and no listener identifiers. Results are cached by link key.
"""

from __future__ import annotations

import enum
import logging
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

import httpx

from songnexus.core import ids
from songnexus.core.links import (
    LinkKind,
    MusicLink,
    Service,
    clean_title,
    extract_url,
    guess_from_byline,
    guess_from_video,
    is_short_link,
    parse_link,
    split_artists,
)
from songnexus.core.resolution import Decision
from songnexus.core.search import EntityType
from songnexus.core.text import base_title, normalize
from songnexus.service.readmodel import ReadModel

log = logging.getLogger(__name__)

MAX_INPUT_CHARS = 2048
MAX_CANDIDATES = 5
MAX_PLAYLIST_TRACKS = 500
CACHE_SIZE = 2048
CACHE_TTL_S = 24 * 3600
REQUEST_TIMEOUT_S = 6.0


class Outcome(enum.StrEnum):
    """How a link resolved."""

    RESOLVED = "RESOLVED"  # an artist, a song, or a playlist's tracks
    CANDIDATES = "CANDIDATES"  # several catalog entries fit; the listener picks
    NOT_IN_CATALOG = "NOT_IN_CATALOG"  # understood, but not in our catalog yet
    UNSUPPORTED = "UNSUPPORTED"  # a music link we cannot read (a Tidal song, an Amazon page)
    NOT_A_MUSIC_LINK = "NOT_A_MUSIC_LINK"
    LOOKUP_FAILED = "LOOKUP_FAILED"  # the service did not answer; worth retrying


@dataclass
class Resolution:
    """What a link turned out to be.

    Attributes:
        outcome: How it resolved.
        link: The recognized link (None when it was not one).
        artist_ids: Catalog artists, the one the link is about first.
        recording_id: The catalog song, for song links that matched one.
        release_id: The catalog release, for album links that matched one.
        candidates: (entity type, ID) pairs to choose from, for CANDIDATES.
        title: The song, album or playlist title the service reported.
        artist_names: The artist names the service reported.
        tracks: A playlist's tracks as (title, artist names), for playlist links.
        via: Source IDs that answered, in order (shown as provenance).
    """

    outcome: Outcome
    link: MusicLink | None = None
    artist_ids: list[str] = field(default_factory=list)
    recording_id: str | None = None
    release_id: str | None = None
    candidates: list[tuple[EntityType, str]] = field(default_factory=list)
    title: str | None = None
    artist_names: list[str] = field(default_factory=list)
    tracks: list[tuple[str, list[str]]] = field(default_factory=list)
    via: list[str] = field(default_factory=list)


@dataclass
class _Facts:
    """What the outside world said about a link."""

    title: str | None = None
    artists: list[str] = field(default_factory=list)
    artist_mbids: list[str] = field(default_factory=list)
    isrc: str | None = None
    tracks: list[tuple[str, list[str]]] = field(default_factory=list)
    via: list[str] = field(default_factory=list)
    failed: bool = False


class _LookupError(Exception):
    """A service did not answer usefully."""


@dataclass
class ResolverConfig:
    """Where the resolver looks.

    Attributes:
        musicbrainz_base_url: MusicBrainz web service root.
        musicbrainz_min_interval_s: Gap between MusicBrainz requests (they ask for >= 1 s).
        network: False keeps resolution to our catalog (tests, offline demos).
        spotify_client_id: With the secret, enables Spotify's Web API for song links.
        spotify_client_secret: See above.
    """

    musicbrainz_base_url: str = "https://musicbrainz.org/ws/2"
    musicbrainz_min_interval_s: float = 1.1
    network: bool = True
    spotify_client_id: str = ""
    spotify_client_secret: str = ""


class LinkResolver:
    """Resolves links; one per process (it holds the cache and the MusicBrainz pacing)."""

    def __init__(
        self,
        http: Callable[[], httpx.Client],
        config: ResolverConfig | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._http_factory = http
        self._config = config or ResolverConfig()
        self._clock = clock
        self._sleep = sleep
        self._cache: OrderedDict[str, tuple[float, str, Resolution]] = OrderedDict()
        self._cache_lock = threading.Lock()
        self._mb_lock = threading.Lock()
        self._mb_last = -1e9
        self._spotify_token: tuple[float, str] | None = None

    # --- Entry point ---------------------------------------------------------------------

    def resolve(self, model: ReadModel, text: str) -> Resolution:
        """Resolves a pasted or shared link (or text containing one)."""
        url = extract_url(text[:MAX_INPUT_CHARS]) or text[:MAX_INPUT_CHARS].strip()
        if not url:
            return Resolution(Outcome.NOT_A_MUSIC_LINK)
        if is_short_link(url) and self._config.network:
            url = self._expand(url) or url
        link = parse_link(url)
        if link is None:
            return Resolution(Outcome.NOT_A_MUSIC_LINK)
        cached = self._cached(link.key, model.version)
        if cached is not None:
            return cached
        with self._http_factory() as http:
            result = self._resolve(model, link, http)
        result.link = link
        # A failed lookup is worth retrying soon; it is not cached.
        if result.outcome is not Outcome.LOOKUP_FAILED:
            self._store(link.key, model.version, result)
        log.info(
            "link resolved",
            extra={
                "service": link.service.value,
                "kind": link.kind.value,
                "outcome": result.outcome.value,
            },
        )
        return result

    def _resolve(self, model: ReadModel, link: MusicLink, http: httpx.Client) -> Resolution:
        if link.service is Service.MUSICBRAINZ:
            return self._musicbrainz_link(model, link, http)
        if link.kind is LinkKind.ARTIST:
            return self._artist(model, link, http)
        if link.kind is LinkKind.PLAYLIST:
            return self._playlist(model, link, http)
        return self._item(model, link, http)

    # --- Artists ---------------------------------------------------------------------------

    def _artist(self, model: ReadModel, link: MusicLink, http: httpx.Client) -> Resolution:
        known = model.artist_links.get(link.key)
        if known:
            return Resolution(Outcome.RESOLVED, artist_ids=[known], via=["musicbrainz"])
        facts = _Facts()
        if self._config.network:
            mbids = self._mb_url_artists(link.url, http, facts)
            found = [a for a in (ids.artist_id(m) for m in mbids) if a in model.graph.nodes]
            if found:
                return Resolution(Outcome.RESOLVED, artist_ids=found[:1], via=["musicbrainz"])
            self._artist_name(link, http, facts)
        if link.hint_artist and not facts.artists:
            facts.artists = [link.hint_artist]
        return self._by_names(model, facts)

    def _artist_name(self, link: MusicLink, http: httpx.Client, facts: _Facts) -> None:
        """Asks the service for the artist's name."""
        try:
            if link.service is Service.SPOTIFY:
                data = self._json(http, "https://open.spotify.com/oembed", {"url": link.url})
                facts.artists = [str(data["title"])]
                facts.via.append("spotify-oembed")
            elif link.service is Service.DEEZER:
                data = self._json(http, f"https://api.deezer.com/artist/{link.id}", {})
                facts.artists = [str(data["name"])]
                facts.via.append("deezer-api")
            elif link.service is Service.APPLE_MUSIC:
                item = self._itunes(http, link)
                facts.artists = [str(item["artistName"])]
                facts.via.append("itunes-search-api")
            elif link.service is Service.SOUNDCLOUD:
                data = self._soundcloud(http, link)
                facts.artists = [str(data["author_name"])]
                facts.via.append("soundcloud-oembed")
        except (_LookupError, KeyError, TypeError):
            facts.failed = True

    # --- Songs and albums -----------------------------------------------------------------

    def _item(self, model: ReadModel, link: MusicLink, http: httpx.Client) -> Resolution:
        facts = _Facts()
        if link.hint_title:
            facts.title = link.hint_title
        if link.hint_artist:
            facts.artists = [link.hint_artist]
        if self._config.network:
            try:
                self._item_facts(link, http, facts)
            except (_LookupError, KeyError, TypeError, IndexError):
                facts.failed = True
            if link.service is Service.BANDCAMP:
                band = model.artist_links.get(f"BANDCAMP:ARTIST:{link.id.split('/')[0]}")
                if band:
                    facts.artist_mbids = []
                    return self._match_item(model, link, facts, preset=[band])
                mbids = self._mb_url_artists(
                    link.url.split("/track/")[0].split("/album/")[0], http, facts
                )
                facts.artist_mbids = mbids
            if facts.isrc:
                self._mb_isrc(facts.isrc, http, facts)
        if link.service in {Service.TIDAL, Service.AMAZON_MUSIC} and not facts.title:
            return Resolution(Outcome.UNSUPPORTED, via=facts.via)
        if not facts.title and not facts.artists:
            return Resolution(
                Outcome.LOOKUP_FAILED if facts.failed else Outcome.UNSUPPORTED, via=facts.via
            )
        return self._match_item(model, link, facts)

    def _item_facts(self, link: MusicLink, http: httpx.Client, facts: _Facts) -> None:
        """Fills title, artists and ISRC from the service's public metadata."""
        album = link.kind is LinkKind.ALBUM
        if link.service is Service.DEEZER:
            data = self._json(
                http, f"https://api.deezer.com/{'album' if album else 'track'}/{link.id}", {}
            )
            facts.title = str(data["title"])
            names = [str(data["artist"]["name"])]
            names += [str(c["name"]) for c in data.get("contributors", []) if isinstance(c, dict)]
            facts.artists = list(dict.fromkeys(names))
            facts.isrc = None if album else data.get("isrc") or None
            facts.via.append("deezer-api")
        elif link.service is Service.APPLE_MUSIC:
            item = self._itunes(http, link)
            facts.title = str(item.get("collectionName" if album else "trackName") or "") or None
            facts.artists = list(split_artists(str(item.get("artistName", ""))))
            facts.via.append("itunes-search-api")
        elif link.service is Service.SPOTIFY:
            if not album and self._spotify_enabled():
                self._spotify_track(link, http, facts)
            else:
                data = self._json(http, "https://open.spotify.com/oembed", {"url": link.url})
                facts.title = str(data["title"])
                facts.via.append("spotify-oembed")
        elif link.service in {Service.YOUTUBE, Service.YOUTUBE_MUSIC}:
            data = self._json(
                http,
                "https://www.youtube.com/oembed",
                {"url": f"https://www.youtube.com/watch?v={link.id}", "format": "json"},
            )
            guess = guess_from_video(str(data["title"]), str(data.get("author_name", "")))
            facts.title, facts.artists = guess.title, list(guess.artists)
            facts.via.append("youtube-oembed")
        elif link.service is Service.SOUNDCLOUD:
            data = self._soundcloud(http, link)
            guess = guess_from_byline(str(data["title"]))
            facts.title = guess.title
            facts.artists = list(guess.artists) or list(
                split_artists(str(data.get("author_name", "")))
            )
            facts.via.append("soundcloud-oembed")
        elif link.service is Service.TIDAL:
            # TIDAL's oEmbed carries no title; nothing public names the song.
            return

    def _match_item(
        self,
        model: ReadModel,
        link: MusicLink,
        facts: _Facts,
        preset: list[str] | None = None,
    ) -> Resolution:
        """Finds the song (or album) once title and artists are known."""
        artist_ids = preset or [
            a for a in (ids.artist_id(m) for m in facts.artist_mbids) if a in model.graph.nodes
        ]
        if not artist_ids:
            artist_ids = self._names_to_artists(model, facts.artists)
        entity = EntityType.RELEASE if link.kind is LinkKind.ALBUM else EntityType.RECORDING
        base = Resolution(
            Outcome.RESOLVED,
            title=facts.title,
            artist_names=facts.artists,
            via=facts.via or ["musicbrainz"],
        )
        if facts.title:
            hits = self._titles(model, facts.title, entity, artist_ids)
            if hits and artist_ids:
                base.artist_ids = list(dict.fromkeys(artist_ids))
                if entity is EntityType.RECORDING:
                    base.recording_id = hits[0]
                else:
                    base.release_id = hits[0]
                return base
            if not artist_ids and hits:
                base.outcome = Outcome.CANDIDATES
                base.candidates = [(entity, h) for h in hits[:MAX_CANDIDATES]]
                return base
        if artist_ids:
            # The artist is ours; the song is not yet. Open the artist.
            base.artist_ids = list(dict.fromkeys(artist_ids))
            return base
        return Resolution(
            Outcome.NOT_IN_CATALOG, title=facts.title, artist_names=facts.artists, via=facts.via
        )

    def _titles(
        self, model: ReadModel, title: str, entity: EntityType, artist_ids: list[str]
    ) -> list[str]:
        """Catalog songs or releases with this title, by the given artists when known."""
        wanted = {normalize(base_title(clean_title(title))), normalize(clean_title(title))}
        artists = set(artist_ids)
        exact: list[str] = []
        loose: list[str] = []
        for hit in model.search.search(title, limit=40, entity_types=frozenset({entity})):
            doc = model.search.get(hit.entity_id)
            by = set(doc.artist_ids) if doc else set()
            if artists and not (by & artists):
                continue
            names = {normalize(base_title(hit.name)), normalize(hit.name)}
            if names & wanted:
                exact.append(hit.entity_id)
            elif any(n and w and (n in w or w in n) for n in names for w in wanted):
                # "Alright - Remastered 2015" against "Alright": the same song, written longer.
                loose.append(hit.entity_id)
        if artists:
            return exact or loose[:1]
        return exact

    # --- Playlists ---------------------------------------------------------------------------

    def _playlist(self, model: ReadModel, link: MusicLink, http: httpx.Client) -> Resolution:
        if link.service is not Service.DEEZER or not self._config.network:
            return Resolution(Outcome.UNSUPPORTED)
        try:
            data = self._json(http, f"https://api.deezer.com/playlist/{link.id}", {})
            tracks = [
                (str(t["title"]), [str(t["artist"]["name"])])
                for t in data["tracks"]["data"][:MAX_PLAYLIST_TRACKS]
                if isinstance(t, dict)
            ]
        except (_LookupError, KeyError, TypeError):
            return Resolution(Outcome.LOOKUP_FAILED)
        if not tracks:
            return Resolution(Outcome.NOT_IN_CATALOG, title=str(data.get("title") or ""))
        return Resolution(
            Outcome.RESOLVED, title=str(data.get("title") or ""), tracks=tracks, via=["deezer-api"]
        )

    # --- MusicBrainz -------------------------------------------------------------------------

    def _musicbrainz_link(
        self, model: ReadModel, link: MusicLink, http: httpx.Client
    ) -> Resolution:
        if link.kind is LinkKind.ARTIST:
            artist = ids.artist_id(link.id)
            if artist in model.graph.nodes:
                return Resolution(Outcome.RESOLVED, artist_ids=[artist], via=["musicbrainz"])
            return Resolution(Outcome.NOT_IN_CATALOG, via=["musicbrainz"])
        facts = _Facts()
        if self._config.network:
            try:
                data = self._mb(http, f"recording/{link.id}", {"inc": "artist-credits"})
                facts.title = str(data["title"])
                self._credits(data, facts)
                facts.via.append("musicbrainz")
            except (_LookupError, KeyError, TypeError):
                return Resolution(Outcome.LOOKUP_FAILED)
        return self._match_item(model, link, facts)

    def _mb_url_artists(self, url: str, http: httpx.Client, facts: _Facts) -> list[str]:
        """MusicBrainz IDs of the artists a URL belongs to (by MusicBrainz's URL index)."""
        try:
            data = self._mb(http, "url", {"resource": url, "inc": "artist-rels"})
        except _LookupError:
            return []
        mbids = [
            str(r["artist"]["id"])
            for r in data.get("relations", [])
            if isinstance(r, dict) and r.get("target-type") == "artist" and "artist" in r
        ]
        if mbids:
            facts.via.append("musicbrainz")
        return list(dict.fromkeys(mbids))

    def _mb_isrc(self, isrc: str, http: httpx.Client, facts: _Facts) -> None:
        """Adds the artists MusicBrainz credits on recordings with this ISRC."""
        try:
            data = self._mb(http, f"isrc/{isrc}", {"inc": "artist-credits"})
        except _LookupError:
            return
        for recording in data.get("recordings", [])[:3]:
            self._credits(recording, facts)
        if facts.artist_mbids:
            facts.via.append("musicbrainz")

    @staticmethod
    def _credits(recording: dict[str, Any], facts: _Facts) -> None:
        for credit in recording.get("artist-credit", []):
            if isinstance(credit, dict) and isinstance(credit.get("artist"), dict):
                mbid = str(credit["artist"].get("id", ""))
                if mbid and mbid not in facts.artist_mbids:
                    facts.artist_mbids.append(mbid)

    def _mb(self, http: httpx.Client, path: str, params: dict[str, str]) -> dict[str, Any]:
        """One MusicBrainz request, paced across threads as MusicBrainz asks."""
        with self._mb_lock:
            wait = self._mb_last + self._config.musicbrainz_min_interval_s - self._clock()
            if wait > 0:
                self._sleep(wait)
            self._mb_last = self._clock()
        url = f"{self._config.musicbrainz_base_url.rstrip('/')}/{path}"
        return self._json(http, url, {**params, "fmt": "json"}, not_found_ok=False)

    # --- Services ------------------------------------------------------------------------------

    def _itunes(self, http: httpx.Client, link: MusicLink) -> dict[str, Any]:
        params = {"id": link.id}
        if link.country:
            params["country"] = link.country
        data = self._json(http, "https://itunes.apple.com/lookup", params)
        results = [r for r in data.get("results", []) if isinstance(r, dict)]
        if not results:
            raise _LookupError("no results")
        return results[0]

    def _soundcloud(self, http: httpx.Client, link: MusicLink) -> dict[str, Any]:
        return self._json(
            http, "https://soundcloud.com/oembed", {"url": link.url, "format": "json"}
        )

    def _spotify_enabled(self) -> bool:
        return bool(self._config.spotify_client_id and self._config.spotify_client_secret)

    def _spotify_track(self, link: MusicLink, http: httpx.Client, facts: _Facts) -> None:
        """Spotify's Web API (client credentials): artists and ISRC for a track."""
        token = self._spotify_access_token(http)
        response = http.get(
            f"https://api.spotify.com/v1/tracks/{link.id}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=REQUEST_TIMEOUT_S,
        )
        if response.status_code != httpx.codes.OK:
            raise _LookupError(f"spotify {response.status_code}")
        data = response.json()
        facts.title = str(data["name"])
        facts.artists = [str(a["name"]) for a in data.get("artists", []) if isinstance(a, dict)]
        facts.isrc = (data.get("external_ids") or {}).get("isrc") or None
        facts.via.append("spotify-web-api")

    def _spotify_access_token(self, http: httpx.Client) -> str:
        now = self._clock()
        if self._spotify_token and self._spotify_token[0] > now:
            return self._spotify_token[1]
        response = http.post(
            "https://accounts.spotify.com/api/token",
            data={"grant_type": "client_credentials"},
            auth=(self._config.spotify_client_id, self._config.spotify_client_secret),
            timeout=REQUEST_TIMEOUT_S,
        )
        if response.status_code != httpx.codes.OK:
            raise _LookupError(f"spotify token {response.status_code}")
        data = response.json()
        token = str(data["access_token"])
        self._spotify_token = (now + float(data.get("expires_in", 3600)) - 60, token)
        return token

    def _expand(self, url: str) -> str | None:
        """Follows a short link's redirects, accepting only a music link as the end."""
        try:
            with self._http_factory() as http:
                response = http.get(url, follow_redirects=True, timeout=REQUEST_TIMEOUT_S)
        except httpx.HTTPError:
            return None
        final = str(response.url)
        return final if parse_link(final) is not None else None

    def _json(
        self,
        http: httpx.Client,
        url: str,
        params: dict[str, str],
        *,
        not_found_ok: bool = False,
    ) -> dict[str, Any]:
        try:
            response = http.get(url, params=params, timeout=REQUEST_TIMEOUT_S)
        except httpx.HTTPError as error:
            raise _LookupError(str(error)) from error
        if response.status_code != httpx.codes.OK:
            raise _LookupError(f"{url} -> {response.status_code}")
        try:
            data = response.json()
        except ValueError as error:
            raise _LookupError("not JSON") from error
        if not isinstance(data, dict) or "error" in data:
            raise _LookupError("error payload")
        return data

    # --- Names -----------------------------------------------------------------------------------

    def _names_to_artists(self, model: ReadModel, names: Iterable[str]) -> list[str]:
        """Catalog artists for names, matched only when unambiguous."""
        found: list[str] = []
        for name in names:
            resolution = model.resolutions.resolve(model.search, [name])[0]
            if resolution.decision is Decision.MATCHED and resolution.entity_id:
                found.append(resolution.entity_id)
                break
        return found

    def _by_names(self, model: ReadModel, facts: _Facts) -> Resolution:
        if not facts.artists:
            return Resolution(
                Outcome.LOOKUP_FAILED if facts.failed else Outcome.NOT_IN_CATALOG, via=facts.via
            )
        for name in facts.artists:
            resolution = model.resolutions.resolve(model.search, [name])[0]
            if resolution.decision is Decision.MATCHED and resolution.entity_id:
                return Resolution(
                    Outcome.RESOLVED,
                    artist_ids=[resolution.entity_id],
                    artist_names=facts.artists,
                    via=facts.via,
                )
            if resolution.decision is Decision.AMBIGUOUS:
                return Resolution(
                    Outcome.CANDIDATES,
                    candidates=[
                        (EntityType.ARTIST, c.candidate.entity_id)
                        for c in resolution.ranked[:MAX_CANDIDATES]
                    ],
                    artist_names=facts.artists,
                    via=facts.via,
                )
        return Resolution(Outcome.NOT_IN_CATALOG, artist_names=facts.artists, via=facts.via)

    # --- Cache -----------------------------------------------------------------------------------

    def _cached(self, key: str, version: str) -> Resolution | None:
        with self._cache_lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            expires, entry_version, value = entry
            if expires < self._clock() or entry_version != version:
                del self._cache[key]
                return None
            self._cache.move_to_end(key)
            return value

    def _store(self, key: str, version: str, value: Resolution) -> None:
        with self._cache_lock:
            self._cache[key] = (self._clock() + CACHE_TTL_S, version, value)
            self._cache.move_to_end(key)
            while len(self._cache) > CACHE_SIZE:
                self._cache.popitem(last=False)
