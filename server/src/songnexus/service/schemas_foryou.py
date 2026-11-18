"""Schemas for For You (ADR 0010): the feed, events, follows, taste feedback and imports."""

from __future__ import annotations

import enum

from pydantic import Field

from songnexus.service.schemas import ApiModel, ArtistSummary

MAX_EVENTS = 100
MAX_IMPORT_ARTISTS = 5000
MAX_PREVIEW_SEEDS = 50


class FeedReasonKind(enum.StrEnum):
    """Why a card is in the feed."""

    CONNECTED = "CONNECTED"
    FANS_ALSO = "FANS_ALSO"
    SIMILAR = "SIMILAR"
    GENRE = "GENRE"
    FRIENDS = "FRIENDS"
    DISCOVER = "DISCOVER"


class SeedKind(enum.StrEnum):
    """Why the artist a reason names is part of the listener's taste."""

    FOLLOW = "FOLLOW"
    TOP = "TOP"
    PLAYS = "PLAYS"
    MORE_LIKE = "MORE_LIKE"
    ENGAGED = "ENGAGED"


class FeedGenre(ApiModel):
    """A top-level genre."""

    id: str
    display_name: str


class FeedReason(ApiModel):
    """The reason shown on a card. Clients word it from ``kind`` and the fields."""

    kind: FeedReasonKind
    via_artist: ArtistSummary | None = Field(
        default=None,
        description="CONNECTED, FANS_ALSO, SIMILAR: the listener's artist this one is close to.",
    )
    via_kind: SeedKind | None = Field(
        default=None, description="Why `viaArtist` counts: followed, Top 5, played, and so on."
    )
    genre: FeedGenre | None = Field(default=None, description="GENRE: the genre.")
    friends: int = Field(default=0, description="FRIENDS: how many friends share the artist.")


class FeedTrack(ApiModel):
    """A recording to start with."""

    name: str = Field(description="`recordings/{recording}`.")
    title: str
    year: int | None = None


class FeedItem(ApiModel):
    """One card."""

    position: int
    artist: ArtistSummary
    reason: FeedReason
    genre: FeedGenre | None = None
    tracks: list[FeedTrack] = Field(default_factory=list)
    exploratory: bool = Field(
        default=False, description="Placed to learn something new about the listener's taste."
    )


class Feed(ApiModel):
    """A page of a For You feed."""

    name: str = Field(
        description="`users/{user}/feeds/{feed}`; events about these cards name it. Empty for "
        "previews."
    )
    items: list[FeedItem]
    next_page_token: str = ""
    cold: bool = Field(
        default=False,
        description="True when nothing is known about the listener yet: the client should "
        "offer to pick artists, import or link a service.",
    )
    personalized: bool = Field(
        default=True, description="False when the listener turned off learning from activity."
    )
    model_version: str = ""
    arm: str = ""


class PreviewFeedRequest(ApiModel):
    """A feed for someone signed out: seeds come from the browser, nothing is stored."""

    seeds: list[str] = Field(
        default_factory=list, max_length=MAX_PREVIEW_SEEDS, description="`artists/{artist}`."
    )
    exclude: list[str] = Field(default_factory=list, max_length=500)
    page_size: int = Field(default=20, ge=1, le=50)


class EventKind(enum.StrEnum):
    """What happened."""

    IMPRESSION = "IMPRESSION"  # a card at least half on screen for a second; dwellMs on leave
    OPEN = "OPEN"  # artist opened (from a card or any page)
    LISTEN = "LISTEN"  # "Listen on YouTube Music"
    SKIP = "SKIP"  # scrolled past at once
    HIDE = "HIDE"  # "not interested" on a card
    SHARE = "SHARE"


class Surface(enum.StrEnum):
    """Where it happened."""

    FOR_YOU = "FOR_YOU"
    ARTIST = "ARTIST"
    HOME = "HOME"
    EXPLORE = "EXPLORE"
    SEARCH = "SEARCH"
    CHART = "CHART"
    OTHER = "OTHER"


class Event(ApiModel):
    """One interaction."""

    event_id: str = Field(
        min_length=8,
        max_length=64,
        pattern=r"^[A-Za-z0-9_-]+$",
        description="Client-chosen unique ID; a retried event is stored once.",
    )
    kind: EventKind
    artist: str = Field(description="`artists/{artist}`.")
    surface: Surface = Surface.OTHER
    feed: str | None = Field(default=None, description="`users/{user}/feeds/{feed}` for cards.")
    position: int | None = Field(default=None, ge=0, le=10_000)
    dwell_ms: int | None = Field(default=None, ge=0, le=3_600_000)
    time: str | None = Field(
        default=None, description="When it happened (RFC 3339); server time when absent or skewed."
    )


class BatchCreateEventsRequest(ApiModel):
    """Up to 100 events."""

    events: list[Event] = Field(max_length=MAX_EVENTS)


class BatchCreateEventsResponse(ApiModel):
    """What was kept."""

    received: int
    stored: int = Field(description="New events stored (duplicates and unknown artists are not).")
    personalize: bool = Field(description="False: learning from activity is off; nothing stored.")


class FollowedArtist(ApiModel):
    """An artist the listener follows."""

    name: str = Field(description="`users/{user}/followedArtists/{artist}`.")
    artist: ArtistSummary | None = Field(
        default=None, description="Null when the artist left the catalog."
    )
    create_time: str


class ListFollowedArtistsResponse(ApiModel):
    """Followed artists, newest first."""

    followed_artists: list[FollowedArtist]
    next_page_token: str = ""
    total_size: int = 0


class CreateFollowedArtistRequest(ApiModel):
    """Follow an artist."""

    artist: str = Field(description="`artists/{artist}`.")


class TasteFeedbackKind(enum.StrEnum):
    """Explicit feedback."""

    NOT_INTERESTED = "NOT_INTERESTED"  # this artist: out of For You for 180 days
    MORE_LIKE_THIS = "MORE_LIKE_THIS"  # this artist: more of what is like it
    LESS_OF_GENRE = "LESS_OF_GENRE"  # this genre: less of it


class TasteFeedback(ApiModel):
    """One piece of feedback."""

    name: str = Field(description="`users/{user}/tasteFeedback/{kind}.{artists|genres}.{id}`.")
    kind: TasteFeedbackKind
    artist: ArtistSummary | None = None
    genre: FeedGenre | None = None
    create_time: str


class ListTasteFeedbackResponse(ApiModel):
    """Feedback, newest first."""

    taste_feedback: list[TasteFeedback]


class CreateTasteFeedbackRequest(ApiModel):
    """Give feedback: an artist for NOT_INTERESTED and MORE_LIKE_THIS, a genre for LESS_OF_GENRE."""

    kind: TasteFeedbackKind
    artist: str | None = Field(default=None, description="`artists/{artist}`.")
    genre: str | None = Field(default=None, description="`genres/{genre}`.")


class ImportedArtist(ApiModel):
    """An artist from an imported file and how often it was played there."""

    artist: str = Field(description="`artists/{artist}`.")
    plays: int = Field(default=1, ge=1, le=10_000_000)


class ImportListeningRequest(ApiModel):
    """Keep an import's artists (and play counts only) for For You."""

    artists: list[ImportedArtist] = Field(max_length=MAX_IMPORT_ARTISTS)


class ListeningImport(ApiModel):
    """What is kept from imports."""

    name: str = Field(description="`users/{user}/listeningImport`.")
    artists: int = Field(description="Artists kept (0: nothing imported or cleared).")
