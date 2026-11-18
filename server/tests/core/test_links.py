"""Reading music links from other apps (core.links)."""

from __future__ import annotations

import pytest

from songnexus.core.links import (
    LinkKind,
    Service,
    clean_title,
    extract_url,
    guess_from_byline,
    guess_from_video,
    is_short_link,
    parse_link,
    split_artists,
)


@pytest.mark.parametrize(
    ("raw", "service", "kind", "item"),
    [
        (
            "https://open.spotify.com/artist/2YZyLoL8N0Wb9xBt1NhZWg?si=abc123",
            Service.SPOTIFY,
            LinkKind.ARTIST,
            "2YZyLoL8N0Wb9xBt1NhZWg",
        ),
        (
            "https://open.spotify.com/intl-de/track/3iVcZ5G6tvkXZkZKlMpIUs",
            Service.SPOTIFY,
            LinkKind.TRACK,
            "3iVcZ5G6tvkXZkZKlMpIUs",
        ),
        (
            "spotify:album:4eLPsYPBmXABThSJ821sqY",
            Service.SPOTIFY,
            LinkKind.ALBUM,
            "4eLPsYPBmXABThSJ821sqY",
        ),
        (
            "https://music.apple.com/us/album/alright/1440871877?i=1440871886&uo=4",
            Service.APPLE_MUSIC,
            LinkKind.TRACK,
            "1440871886",
        ),
        (
            "https://music.apple.com/gb/artist/kendrick-lamar/368183298",
            Service.APPLE_MUSIC,
            LinkKind.ARTIST,
            "368183298",
        ),
        (
            "https://music.apple.com/us/song/alright/1440871886",
            Service.APPLE_MUSIC,
            LinkKind.TRACK,
            "1440871886",
        ),
        (
            "https://itunes.apple.com/us/artist/id368183298",
            Service.APPLE_MUSIC,
            LinkKind.ARTIST,
            "368183298",
        ),
        (
            "https://music.youtube.com/watch?v=Z-48u_uWMHY&feature=share",
            Service.YOUTUBE_MUSIC,
            LinkKind.TRACK,
            "Z-48u_uWMHY",
        ),
        ("https://youtu.be/Z-48u_uWMHY?si=x", Service.YOUTUBE, LinkKind.TRACK, "Z-48u_uWMHY"),
        (
            "https://m.youtube.com/watch?v=Z-48u_uWMHY",
            Service.YOUTUBE,
            LinkKind.TRACK,
            "Z-48u_uWMHY",
        ),
        (
            "https://music.youtube.com/channel/UCRWdKDkFHPXqdIFvVTnSf4g",
            Service.YOUTUBE_MUSIC,
            LinkKind.ARTIST,
            "UCRWdKDkFHPXqdIFvVTnSf4g",
        ),
        ("https://www.deezer.com/en/track/3135556", Service.DEEZER, LinkKind.TRACK, "3135556"),
        ("https://deezer.com/artist/27", Service.DEEZER, LinkKind.ARTIST, "27"),
        ("https://tidal.com/browse/track/77646169", Service.TIDAL, LinkKind.TRACK, "77646169"),
        ("https://listen.tidal.com/artist/3346", Service.TIDAL, LinkKind.ARTIST, "3346"),
        (
            "https://soundcloud.com/kendrick-lamar-music",
            Service.SOUNDCLOUD,
            LinkKind.ARTIST,
            "kendrick-lamar-music",
        ),
        (
            "https://soundcloud.com/someone/a-song?in=x",
            Service.SOUNDCLOUD,
            LinkKind.TRACK,
            "someone/a-song",
        ),
        ("https://radiohead.bandcamp.com/", Service.BANDCAMP, LinkKind.ARTIST, "radiohead"),
        (
            "https://www.last.fm/music/Kendrick+Lamar/_/Alright",
            Service.LASTFM,
            LinkKind.TRACK,
            "Kendrick Lamar/Alright",
        ),
        (
            "https://music.amazon.com/albums/B00VBNPJ1G?trackAsin=B00VBNPLAE",
            Service.AMAZON_MUSIC,
            LinkKind.TRACK,
            "B00VBNPLAE",
        ),
        (
            "musicbrainz.org/artist/381086EA-F511-4ABA-BDF9-71C753DC5077",
            Service.MUSICBRAINZ,
            LinkKind.ARTIST,
            "381086ea-f511-4aba-bdf9-71c753dc5077",
        ),
    ],
)
def test_parse_link(raw: str, service: Service, kind: LinkKind, item: str) -> None:
    link = parse_link(raw)
    assert link is not None
    assert (link.service, link.kind, link.id) == (service, kind, item)


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "hello",
        "https://example.com/artist/1",
        "https://open.spotify.com/user/someone",
        "https://open.spotify.com/track/short",
        "https://music.apple.com/us/browse",
        "https://soundcloud.com/discover",
        "https://www.last.fm/user/someone",
        "spotify:track:bad",
    ],
)
def test_not_a_music_link(raw: str) -> None:
    assert parse_link(raw) is None


def test_tracking_parameters_never_survive() -> None:
    link = parse_link(
        "https://open.spotify.com/track/3iVcZ5G6tvkXZkZKlMpIUs?si=abc&utm_source=copy"
    )
    assert link is not None
    assert "?" not in link.url
    youtube = parse_link("https://www.youtube.com/watch?v=Z-48u_uWMHY&pp=tracking&t=30")
    assert youtube is not None
    assert youtube.url == "https://www.youtube.com/watch?v=Z-48u_uWMHY"


def test_same_thing_from_any_locale_has_one_key() -> None:
    a = parse_link("https://music.apple.com/us/artist/kendrick-lamar/368183298")
    b = parse_link("https://music.apple.com/gb/artist/368183298")
    assert a is not None
    assert b is not None
    assert a.key == b.key
    c = parse_link("https://www.deezer.com/fr/artist/27")
    d = parse_link("https://deezer.com/artist/27")
    assert c is not None
    assert d is not None
    assert c.key == d.key


def test_youtube_music_and_youtube_channels_share_the_stored_url() -> None:
    link = parse_link("https://music.youtube.com/channel/UCRWdKDkFHPXqdIFvVTnSf4g")
    assert link is not None
    assert link.url == "https://www.youtube.com/channel/UCRWdKDkFHPXqdIFvVTnSf4g"


def test_lastfm_and_bandcamp_links_spell_out_names() -> None:
    lastfm = parse_link("https://www.last.fm/de/music/Daft+Punk/_/Harder,+Better,+Faster,+Stronger")
    assert lastfm is not None
    assert (lastfm.hint_artist, lastfm.hint_title) == (
        "Daft Punk",
        "Harder, Better, Faster, Stronger",
    )
    bandcamp = parse_link("https://someband.bandcamp.com/track/my-first-song")
    assert bandcamp is not None
    assert bandcamp.hint_title == "my first song"


def test_extract_url_from_shared_text() -> None:
    text = "Listen to Alright by Kendrick Lamar on Spotify: https://open.spotify.com/track/3iVcZ5G6tvkXZkZKlMpIUs."
    assert extract_url(text) == "https://open.spotify.com/track/3iVcZ5G6tvkXZkZKlMpIUs"
    assert extract_url("nothing here") is None
    assert (
        extract_url("spotify:artist:2YZyLoL8N0Wb9xBt1NhZWg")
        == "spotify:artist:2YZyLoL8N0Wb9xBt1NhZWg"
    )


def test_short_links() -> None:
    assert is_short_link("https://spotify.link/AbCdEf")
    assert is_short_link("https://youtu.be/Z-48u_uWMHY")
    assert not is_short_link("https://open.spotify.com/track/x")
    assert not is_short_link("not a url")


@pytest.mark.parametrize(
    ("title", "channel", "song", "lead"),
    [
        (
            "Kendrick Lamar - Alright (Official Music Video)",
            "KendrickLamarVEVO",
            "Alright",
            "Kendrick Lamar",
        ),
        ("Alright", "Kendrick Lamar - Topic", "Alright", "Kendrick Lamar"),
        (
            "Daft Punk – Harder Better Faster Stronger [Official Audio]",
            "Daft Punk",
            "Harder Better Faster Stronger",
            "Daft Punk",
        ),
        ("HUMBLE.", "KendrickLamarVEVO", "HUMBLE.", "KendrickLamar"),
    ],
)
def test_guess_from_video(title: str, channel: str, song: str, lead: str) -> None:
    guess = guess_from_video(title, channel)
    assert guess.title == song
    assert guess.artists[0] == lead


def test_split_artists_keeps_the_whole_credit_first() -> None:
    assert split_artists("Simon & Garfunkel") == ("Simon & Garfunkel", "Simon", "Garfunkel")
    assert split_artists("Kendrick Lamar feat. SZA") == (
        "Kendrick Lamar feat. SZA",
        "Kendrick Lamar",
        "SZA",
    )
    assert split_artists("A, B") == ("A, B", "A", "B")
    assert split_artists("  ") == ()


def test_clean_title_and_byline() -> None:
    assert clean_title("Alright (Lyrics)") == "Alright"
    assert clean_title("Song (Remix)") == "Song (Remix)"
    guess = guess_from_byline("Some Song by Some Artist")
    assert guess.title == "Some Song"
    assert guess.artists[0] == "Some Artist"
    assert guess_from_byline("Untitled").artists == ()
