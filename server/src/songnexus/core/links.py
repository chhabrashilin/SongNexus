"""Music links from other apps: what a URL points at, without fetching anything.

A listener shares or pastes a link from the app they use (Spotify, Apple Music,
YouTube Music, Deezer, Tidal, SoundCloud, Bandcamp, Last.fm, Amazon Music,
MusicBrainz). This module reads the link itself: which service, what kind of
thing (artist, track, album, playlist) and the service's own ID. It also gives
every link a *key* that does not change with locale segments, slugs, tracking
parameters or ``www.``, so a link a listener shares matches the same link stored
from MusicBrainz.

Pure: no network. ``service.link_resolver`` does the lookups.
"""

from __future__ import annotations

import enum
import re
from dataclasses import dataclass
from urllib.parse import parse_qs, unquote_plus, urlsplit


class Service(enum.StrEnum):
    """The app a link belongs to."""

    SPOTIFY = "SPOTIFY"
    APPLE_MUSIC = "APPLE_MUSIC"
    YOUTUBE_MUSIC = "YOUTUBE_MUSIC"
    YOUTUBE = "YOUTUBE"
    DEEZER = "DEEZER"
    TIDAL = "TIDAL"
    SOUNDCLOUD = "SOUNDCLOUD"
    BANDCAMP = "BANDCAMP"
    LASTFM = "LASTFM"
    AMAZON_MUSIC = "AMAZON_MUSIC"
    MUSICBRAINZ = "MUSICBRAINZ"


class LinkKind(enum.StrEnum):
    """What a link points at."""

    ARTIST = "ARTIST"
    TRACK = "TRACK"
    ALBUM = "ALBUM"
    PLAYLIST = "PLAYLIST"


@dataclass(frozen=True)
class MusicLink:
    """A recognized link.

    Attributes:
        service: The app it belongs to.
        kind: What it points at.
        id: The service's own ID (a slug for Bandcamp, a name for Last.fm).
        url: The link without tracking parameters (safe to send to the service).
        country: Store front for Apple Music links ("us"), when the link names one.
        hint_artist: An artist name the link itself spells out (Last.fm, Bandcamp).
        hint_title: A title the link itself spells out (Last.fm, Bandcamp).
    """

    service: Service
    kind: LinkKind
    id: str
    url: str
    country: str | None = None
    hint_artist: str | None = None
    hint_title: str | None = None

    @property
    def key(self) -> str:
        """A stable key: the same thing shared from any locale or device has the same key."""
        # YouTube Music and YouTube share channel and video IDs.
        service = Service.YOUTUBE if self.service is Service.YOUTUBE_MUSIC else self.service
        # YouTube IDs are case-sensitive; the rest are compared without case.
        item = self.id if service is Service.YOUTUBE else self.id.lower()
        return f"{service.value}:{self.kind.value}:{item}"


# Short links that only redirect; the resolver may follow them, to these hosts only.
SHORT_LINK_HOSTS = frozenset(
    {
        "spotify.link",
        "spoti.fi",
        "youtu.be",
        "on.soundcloud.com",
        "deezer.page.link",
        "link.deezer.com",
        "tidal.link",
        "apple.co",
    }
)

_URL_IN_TEXT = re.compile(r"(https?://[^\s<>\"']+|spotify:[a-z]+:[A-Za-z0-9]+)", re.IGNORECASE)
_SPOTIFY_ID = re.compile(r"^[A-Za-z0-9]{22}$")
_YOUTUBE_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_MBID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_DIGITS = re.compile(r"^\d+$")
_COUNTRY = re.compile(r"^[a-z]{2}$")
_SPOTIFY_KINDS = {
    "artist": LinkKind.ARTIST,
    "track": LinkKind.TRACK,
    "album": LinkKind.ALBUM,
    "playlist": LinkKind.PLAYLIST,
}
_APPLE_KINDS = {
    "artist": LinkKind.ARTIST,
    "song": LinkKind.TRACK,
    "album": LinkKind.ALBUM,
    "playlist": LinkKind.PLAYLIST,
    "music-video": LinkKind.TRACK,
}


def extract_url(text: str) -> str | None:
    """Returns the first link in shared text ("Listen to Alright on Spotify https://…").

    Apps share a sentence, not a bare link; trailing punctuation is trimmed.
    """
    match = _URL_IN_TEXT.search(text or "")
    if not match:
        return None
    return match.group(1).rstrip(".,;:!?)]}»”’")


def _host(netloc: str) -> str:
    host = netloc.lower().split("@")[-1].split(":")[0]
    return host.removeprefix("www.").removeprefix("m.")


def is_short_link(url: str) -> bool:
    """True when ``url`` is a redirecting short link from a known music app."""
    try:
        return _host(urlsplit(url).netloc) in SHORT_LINK_HOSTS
    except ValueError:
        return False


def _segments(path: str) -> list[str]:
    return [unquote_plus(s) for s in path.split("/") if s]


def _slug_words(slug: str) -> str:
    return re.sub(r"[-_]+", " ", slug).strip()


def parse_link(raw: str) -> MusicLink | None:
    """Reads a music link; None when it is not one we know.

    Accepts ``https`` links (with or without ``www.``/``m.``) and ``spotify:`` URIs.
    The returned ``url`` carries no query string except what identifies the item
    (YouTube's ``v``), so share-tracking parameters (``si``, ``utm_*``) never
    reach the service.
    """
    raw = (raw or "").strip()
    if raw.lower().startswith("spotify:"):
        parts = raw.split(":")
        if len(parts) == 3 and parts[1] in _SPOTIFY_KINDS and _SPOTIFY_ID.match(parts[2]):
            return _spotify(_SPOTIFY_KINDS[parts[1]], parts[2])
        return None
    if not re.match(r"^https?://", raw, re.IGNORECASE):
        raw = f"https://{raw}"
    try:
        parts_ = urlsplit(raw)
    except ValueError:
        return None
    host = _host(parts_.netloc)
    segs = _segments(parts_.path)
    query = parse_qs(parts_.query)
    parsers = (
        _parse_spotify,
        _parse_apple,
        _parse_youtube,
        _parse_deezer,
        _parse_tidal,
        _parse_soundcloud,
        _parse_bandcamp,
        _parse_lastfm,
        _parse_amazon,
        _parse_musicbrainz,
    )
    for parser in parsers:
        link = parser(host, segs, query)
        if link is not None:
            return link
    return None


def _spotify(kind: LinkKind, item: str) -> MusicLink:
    return MusicLink(
        Service.SPOTIFY, kind, item, f"https://open.spotify.com/{kind.value.lower()}/{item}"
    )


def _parse_spotify(host: str, segs: list[str], _q: dict[str, list[str]]) -> MusicLink | None:
    if host not in {"open.spotify.com", "play.spotify.com"}:
        return None
    if segs and segs[0].startswith("intl-"):
        segs = segs[1:]
    if len(segs) >= 2 and segs[0] in _SPOTIFY_KINDS and _SPOTIFY_ID.match(segs[1]):
        return _spotify(_SPOTIFY_KINDS[segs[0]], segs[1])
    return None


def _parse_apple(host: str, segs: list[str], q: dict[str, list[str]]) -> MusicLink | None:
    if host not in {"music.apple.com", "itunes.apple.com", "geo.music.apple.com"}:
        return None
    country = None
    if segs and _COUNTRY.match(segs[0]):
        country, segs = segs[0], segs[1:]
    if not segs or segs[0] not in _APPLE_KINDS:
        return None
    kind = _APPLE_KINDS[segs[0]]
    item = segs[-1].removeprefix("id")
    if kind is LinkKind.PLAYLIST:
        item = segs[-1]
    elif not _DIGITS.match(item):
        return None
    # An album link with ?i= is one song on it.
    track = (q.get("i") or [""])[0]
    if kind is LinkKind.ALBUM and _DIGITS.match(track):
        kind, item = LinkKind.TRACK, track
    path = {
        LinkKind.ARTIST: "artist",
        LinkKind.TRACK: "song",
        LinkKind.ALBUM: "album",
        LinkKind.PLAYLIST: "playlist",
    }[kind]
    prefix = f"{country}/" if country else ""
    return MusicLink(
        Service.APPLE_MUSIC,
        kind,
        item,
        f"https://music.apple.com/{prefix}{path}/{item}",
        country=country,
    )


def _parse_youtube(host: str, segs: list[str], q: dict[str, list[str]]) -> MusicLink | None:
    music = host == "music.youtube.com"
    if host not in {"youtube.com", "music.youtube.com", "youtu.be"}:
        return None
    service = Service.YOUTUBE_MUSIC if music else Service.YOUTUBE
    video = None
    if host == "youtu.be" and segs:
        video = segs[0]
    elif segs[:1] == ["watch"]:
        video = (q.get("v") or [""])[0]
    elif len(segs) >= 2 and segs[0] in {"shorts", "live", "embed"}:
        video = segs[1]
    if video and _YOUTUBE_ID.match(video):
        base = "https://music.youtube.com" if music else "https://www.youtube.com"
        return MusicLink(service, LinkKind.TRACK, video, f"{base}/watch?v={video}")
    if len(segs) >= 2 and segs[0] == "channel" and segs[1].startswith("UC"):
        # Stored MusicBrainz links use www.youtube.com for both apps' channels.
        return MusicLink(
            service, LinkKind.ARTIST, segs[1], f"https://www.youtube.com/channel/{segs[1]}"
        )
    if segs and segs[0].startswith("@") and len(segs[0]) > 1:
        return MusicLink(service, LinkKind.ARTIST, segs[0], f"https://www.youtube.com/{segs[0]}")
    playlist = (q.get("list") or [""])[0]
    if segs[:1] == ["playlist"] and playlist:
        return MusicLink(
            service,
            LinkKind.PLAYLIST,
            playlist,
            f"https://{'music' if music else 'www'}.youtube.com/playlist?list={playlist}",
        )
    return None


def _parse_deezer(host: str, segs: list[str], _q: dict[str, list[str]]) -> MusicLink | None:
    if host != "deezer.com":
        return None
    if segs and _COUNTRY.match(segs[0]):
        segs = segs[1:]
    if len(segs) >= 2 and segs[0] in _SPOTIFY_KINDS and _DIGITS.match(segs[1]):
        kind = _SPOTIFY_KINDS[segs[0]]
        return MusicLink(
            Service.DEEZER, kind, segs[1], f"https://www.deezer.com/{segs[0]}/{segs[1]}"
        )
    return None


def _parse_tidal(host: str, segs: list[str], _q: dict[str, list[str]]) -> MusicLink | None:
    if host not in {"tidal.com", "listen.tidal.com"}:
        return None
    if segs[:1] == ["browse"]:
        segs = segs[1:]
    if len(segs) >= 2 and segs[0] in _SPOTIFY_KINDS and re.match(r"^[\w-]+$", segs[1]):
        kind = _SPOTIFY_KINDS[segs[0]]
        return MusicLink(Service.TIDAL, kind, segs[1], f"https://tidal.com/{segs[0]}/{segs[1]}")
    return None


_SOUNDCLOUD_RESERVED = {
    "discover",
    "search",
    "you",
    "stream",
    "upload",
    "charts",
    "pages",
    "terms-of-use",
    "settings",
    "messages",
    "notifications",
}


def _parse_soundcloud(host: str, segs: list[str], _q: dict[str, list[str]]) -> MusicLink | None:
    if host != "soundcloud.com" or not segs or segs[0] in _SOUNDCLOUD_RESERVED:
        return None
    user = segs[0].lower()
    if len(segs) == 1 or segs[1] in {"tracks", "albums", "popular-tracks"}:
        return MusicLink(
            Service.SOUNDCLOUD, LinkKind.ARTIST, user, f"https://soundcloud.com/{user}"
        )
    if segs[1] == "sets" and len(segs) >= 3:
        return MusicLink(
            Service.SOUNDCLOUD,
            LinkKind.PLAYLIST,
            f"{user}/sets/{segs[2]}",
            f"https://soundcloud.com/{user}/sets/{segs[2]}",
        )
    return MusicLink(
        Service.SOUNDCLOUD,
        LinkKind.TRACK,
        f"{user}/{segs[1]}",
        f"https://soundcloud.com/{user}/{segs[1]}",
    )


def _parse_bandcamp(host: str, segs: list[str], _q: dict[str, list[str]]) -> MusicLink | None:
    if not host.endswith(".bandcamp.com") or host in {"daily.bandcamp.com", "bandcamp.com"}:
        return None
    band = host.removesuffix(".bandcamp.com")
    root = f"https://{band}.bandcamp.com"
    if len(segs) >= 2 and segs[0] in {"track", "album"}:
        kind = LinkKind.TRACK if segs[0] == "track" else LinkKind.ALBUM
        return MusicLink(
            Service.BANDCAMP,
            kind,
            f"{band}/{segs[1]}",
            f"{root}/{segs[0]}/{segs[1]}",
            hint_title=_slug_words(segs[1]),
        )
    return MusicLink(Service.BANDCAMP, LinkKind.ARTIST, band, root)


def _parse_lastfm(host: str, segs: list[str], _q: dict[str, list[str]]) -> MusicLink | None:
    if host not in {"last.fm", "lastfm.com"} and not host.endswith(".last.fm"):
        return None
    if segs and _COUNTRY.match(segs[0]):
        segs = segs[1:]
    if len(segs) < 2 or segs[0] != "music" or segs[1].startswith("+"):
        return None
    artist = segs[1]
    url = f"https://www.last.fm/music/{segs[1].replace(' ', '+')}"
    if len(segs) >= 4 and segs[2] == "_":
        return MusicLink(
            Service.LASTFM,
            LinkKind.TRACK,
            f"{artist}/{segs[3]}",
            f"{url}/_/{segs[3].replace(' ', '+')}",
            hint_artist=artist,
            hint_title=segs[3],
        )
    if len(segs) >= 3 and not segs[2].startswith("+"):
        return MusicLink(
            Service.LASTFM,
            LinkKind.ALBUM,
            f"{artist}/{segs[2]}",
            f"{url}/{segs[2].replace(' ', '+')}",
            hint_artist=artist,
            hint_title=segs[2],
        )
    return MusicLink(Service.LASTFM, LinkKind.ARTIST, artist, url, hint_artist=artist)


def _parse_amazon(host: str, segs: list[str], q: dict[str, list[str]]) -> MusicLink | None:
    if not host.startswith("music.amazon."):
        return None
    if len(segs) >= 2 and segs[0] in {"artists", "albums", "tracks", "playlists"}:
        kind = {
            "artists": LinkKind.ARTIST,
            "albums": LinkKind.ALBUM,
            "tracks": LinkKind.TRACK,
            "playlists": LinkKind.PLAYLIST,
        }[segs[0]]
        item = segs[1]
        track = (q.get("trackAsin") or [""])[0]
        if kind is LinkKind.ALBUM and track:
            kind, item = LinkKind.TRACK, track
        return MusicLink(Service.AMAZON_MUSIC, kind, item, f"https://{host}/{segs[0]}/{segs[1]}")
    return None


def _parse_musicbrainz(host: str, segs: list[str], _q: dict[str, list[str]]) -> MusicLink | None:
    if host != "musicbrainz.org" or len(segs) < 2 or not _MBID.match(segs[1].lower()):
        return None
    kind = {"artist": LinkKind.ARTIST, "recording": LinkKind.TRACK}.get(segs[0])
    if kind is None:
        return None
    mbid = segs[1].lower()
    return MusicLink(Service.MUSICBRAINZ, kind, mbid, f"https://musicbrainz.org/{segs[0]}/{mbid}")


# --- Titles as other apps write them ------------------------------------------------------

_NOISE = re.compile(
    r"\s*[\(\[【](?:[^)\]】]*?\b(?:official|video|audio|lyrics?|visuali[sz]er|hd|hq|4k|"
    r"explicit|clean|mv|m/v|music video|live performance|performance video)\b[^)\]】]*)[\)\]】]",
    re.IGNORECASE,
)
_DASHES = re.compile(r"\s+[-–—|]\s+")
_FEATURING = re.compile(r"\s*,\s*|\s+(?:feat\.?|ft\.?|featuring|with|x|&|and)\s+", re.IGNORECASE)
_CHANNEL_SUFFIX = re.compile(r"(?:\s*-\s*topic|vevo|\s+official|\s*TV)$", re.IGNORECASE)


@dataclass(frozen=True)
class TitleGuess:
    """Who and what a video or track title names, as best it can be read."""

    title: str
    artists: tuple[str, ...]


def clean_title(title: str) -> str:
    """Removes "(Official Video)", "[Lyrics]" and the like from a title."""
    return re.sub(r"\s{2,}", " ", _NOISE.sub("", title)).strip(" -–—|")


def split_artists(credit: str) -> tuple[str, ...]:
    """Splits "Kendrick Lamar feat. SZA & X" into names, the credited name first.

    The whole credit comes first too: "Simon & Garfunkel" is one act, and the
    resolver tries the full credit before its parts.
    """
    credit = credit.strip()
    if not credit:
        return ()
    parts = [p.strip() for p in _FEATURING.split(credit) if p.strip()]
    return tuple(dict.fromkeys([credit, *parts]))


def guess_from_video(title: str, channel: str = "") -> TitleGuess:
    """Reads artist and song from a YouTube title and channel.

    "Artist - Topic" channels are YouTube Music's auto-generated artist channels,
    titled with the song alone. Otherwise the convention is "Artist - Song
    (Official Video)", and the channel ("KendrickLamarVEVO") is the fallback.
    """
    channel = channel.strip()
    topic = channel.lower().endswith(" - topic")
    cleaned = clean_title(title)
    if topic:
        return TitleGuess(cleaned, split_artists(channel[: -len(" - topic")]))
    parts = _DASHES.split(cleaned, maxsplit=1)
    if len(parts) == 2 and parts[0] and parts[1]:
        return TitleGuess(clean_title(parts[1]).strip('"“”'), split_artists(parts[0]))
    owner = _CHANNEL_SUFFIX.sub("", channel).strip()
    return TitleGuess(cleaned.strip('"“”'), split_artists(owner) if owner else ())


def guess_from_byline(title: str) -> TitleGuess:
    """Reads "Song by Artist" (SoundCloud's oEmbed title)."""
    head, sep, tail = title.rpartition(" by ")
    if sep and head and tail:
        return TitleGuess(clean_title(head), split_artists(tail))
    return TitleGuess(clean_title(title), ())
