"""API resource and response schemas (the contract; see ``server/openapi.json``).

JSON fields are lowerCamelCase. Entities are referenced by resource name
(``artists/{artist}``), never by bare database IDs, so clients can treat names
as opaque. ``graphVersion`` identifies the catalog version a response came from.
"""

from __future__ import annotations

import enum

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class ApiModel(BaseModel):
    """Base for every API schema: camelCase JSON, immutable."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        frozen=True,
        serialize_by_alias=True,
        # Responses always include defaulted fields, so the contract marks them
        # required in output schemas (request schemas keep them optional).
        json_schema_serialization_defaults_required=True,
    )


# ---------------------------------------------------------------------------
# Enums (UPPER_SNAKE_CASE per AIP-126)
# ---------------------------------------------------------------------------


class ConnectionCategory(enum.StrEnum):
    """A toggleable group of connection kinds."""

    FEATURES = "FEATURES"
    PRODUCERS = "PRODUCERS"
    CONTRIBUTIONS = "CONTRIBUTIONS"
    SAMPLES = "SAMPLES"
    BANDS = "BANDS"
    LABELS = "LABELS"
    ENGINEERING = "ENGINEERING"


class ConnectionKind(enum.StrEnum):
    """Why two artists are connected."""

    PERFORMED_WITH = "PERFORMED_WITH"
    PRODUCED_FOR = "PRODUCED_FOR"
    CO_PRODUCED = "CO_PRODUCED"
    CONTRIBUTED_TO = "CONTRIBUTED_TO"
    SAMPLED = "SAMPLED"
    MEMBER_OF = "MEMBER_OF"
    COLLABORATION = "COLLABORATION"
    SUPPORTED = "SUPPORTED"
    TAUGHT = "TAUGHT"
    LABEL_MATES = "LABEL_MATES"
    ENGINEERED = "ENGINEERED"


class PathMode(enum.StrEnum):
    """How FindPath ranks routes."""

    FEWEST_STEPS = "FEWEST_STEPS"
    STRONGEST_LINKS = "STRONGEST_LINKS"


class PathOutcome(enum.StrEnum):
    """Why a FindPath response does or does not contain a path."""

    FOUND = "FOUND"
    NOT_CONNECTED_WITHIN_LIMIT = "NOT_CONNECTED_WITHIN_LIMIT"  # "not connected in our data (yet)"
    SEARCH_LIMIT_REACHED = "SEARCH_LIMIT_REACHED"


class EntityType(enum.StrEnum):
    """A searchable entity type."""

    ARTIST = "ARTIST"
    RELEASE = "RELEASE"
    RECORDING = "RECORDING"


class CollaborationType(enum.StrEnum):
    """A collaborations tab."""

    FEATURE = "FEATURE"
    PRODUCTION = "PRODUCTION"
    BAND = "BAND"
    CREDIT = "CREDIT"


# ---------------------------------------------------------------------------
# Shared parts
# ---------------------------------------------------------------------------


class SourceLink(ApiModel):
    """A page where a person can check a fact."""

    source: str = Field(description="Data source ID, e.g. `musicbrainz`.")
    source_id: str
    url: str


class GenreShare(ApiModel):
    """A genre and its share of an artist's genre votes."""

    genre: str = Field(description="Resource name `genres/{genre}`.")
    display_name: str
    share: float


class ArtistSummary(ApiModel):
    """An artist as shown in lists."""

    name: str = Field(description="Resource name `artists/{artist}`.", examples=["artists/0b2c…"])
    display_name: str
    disambiguation: str | None = None
    artist_type: str | None = None
    country: str | None = None
    genre_known: bool = Field(
        default=False, description="Whether our data has genres for this artist (AC-12.2)."
    )


class Subject(ApiModel):
    """What a piece of evidence is about."""

    name: str = Field(
        description="Resource name: `recordings/{id}`, `releases/{id}`, `labels/{id}` or "
        "`relations/{id}`."
    )
    display_name: str | None = None


class Evidence(ApiModel):
    """One reason two artists are connected, as a localizable message."""

    message_id: str = Field(description="Client message key, e.g. `evidence.featured`.")
    kind: ConnectionKind
    from_artist: str
    to_artist: str
    from_role: str
    to_role: str
    subject: Subject
    sources: list[SourceLink] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Artists and connections
# ---------------------------------------------------------------------------


class Alias(ApiModel):
    """Another name for an artist."""

    display_name: str
    alias_type: str
    locale: str | None = None


class Link(ApiModel):
    """An external link."""

    link_type: str
    url: str


class Artist(ArtistSummary):
    """GetArtist."""

    begin_date: str | None = None
    detail_level: str = Field(
        description="`full`, `profile` or `stub`: how much the catalog knows about this artist."
    )
    genres: list[GenreShare]
    aliases: list[Alias]
    links: list[Link]
    connection_count: int = Field(description="Direct connections under the default categories.")
    sources: list[SourceLink]
    graph_version: str


class Connection(ApiModel):
    """A connected artist and why."""

    artist: ArtistSummary
    strength: float
    kinds: list[ConnectionKind]
    evidence_count: int
    highlights: list[Evidence] = Field(description="Up to two representative evidence lines.")


class ListArtistConnectionsResponse(ApiModel):
    """ListArtistConnections."""

    connections: list[Connection]
    next_page_token: str = ""
    total_size: int
    graph_version: str


class ConnectionDetail(ApiModel):
    """GetArtistConnection: all evidence between two artists, with sources."""

    artist: ArtistSummary
    other: ArtistSummary
    strength: float
    kinds: list[ConnectionKind]
    evidence: list[Evidence]
    graph_version: str


class Collaboration(ApiModel):
    """A collaborator under one type."""

    artist: ArtistSummary
    type: CollaborationType
    count: int
    first_year: int | None = None
    last_year: int | None = None
    evidence: list[Evidence]


class ListArtistCollaborationsResponse(ApiModel):
    """ListArtistCollaborations. Counts are based on releases in our data."""

    collaborations: list[Collaboration]
    counts: dict[CollaborationType, int]
    next_page_token: str = ""
    total_size: int
    graph_version: str


class PathStep(ApiModel):
    """One step of a path."""

    from_artist: ArtistSummary
    to_artist: ArtistSummary
    strength: float
    evidence: list[Evidence]


class FindPathResponse(ApiModel):
    """FindPath."""

    outcome: PathOutcome
    steps: list[PathStep]
    alternatives: list[list[ArtistSummary]] = Field(
        default_factory=list, description="Other routes, as artist sequences."
    )
    graph_version: str


class SharedGenre(ApiModel):
    """A genre both compared artists carry."""

    genre: str
    display_name: str
    share_a: float
    share_b: float


class CompareArtistsResponse(ApiModel):
    """CompareArtists."""

    artist_a: ArtistSummary
    artist_b: ArtistSummary
    genre_overlap: float | None = Field(description="Weighted overlap in [0, 1]; null if unknown.")
    shared_genres: list[SharedGenre]
    mutual_collaborators: list[ArtistSummary]
    directly_connected: bool
    path: list[ArtistSummary]
    counts_a: dict[CollaborationType, int]
    counts_b: dict[CollaborationType, int]
    graph_version: str


# ---------------------------------------------------------------------------
# Recordings, search, genres
# ---------------------------------------------------------------------------


class Credit(ApiModel):
    """An artist's credit on a recording."""

    artist: ArtistSummary
    role: str
    role_detail: str = ""
    credited_as: str | None = None


class Appearance(ApiModel):
    """A release a recording appears on."""

    release: str
    display_name: str
    year: int | None = None
    disc_number: int
    position: int


class Recording(ApiModel):
    """GetRecording."""

    name: str
    display_name: str
    length_ms: int | None = None
    first_release_date: str | None = None
    credits: list[Credit]
    appearances: list[Appearance]
    sources: list[SourceLink]


class SearchResult(ApiModel):
    """A search hit."""

    name: str = Field(description="Resource name of the entity.")
    entity_type: EntityType
    display_name: str
    subtitle: str
    match_type: str
    matched_on: str
    blocked: bool = Field(
        default=False,
        description="The viewer blocked this artist. Blocked artists appear only for an "
        "exact-name search, so they can be unblocked (AC-17.2).",
    )


class SearchCatalogResponse(ApiModel):
    """SearchCatalog."""

    results: list[SearchResult]
    graph_version: str


class Genre(ApiModel):
    """A genre."""

    name: str
    display_name: str
    artist_count: int


class ListGenresResponse(ApiModel):
    """ListGenres."""

    genres: list[Genre]
    next_page_token: str = ""
    total_size: int


# ---------------------------------------------------------------------------
# Ops
# ---------------------------------------------------------------------------


class Limits(ApiModel):
    """Request limits clients should respect (plan §14)."""

    max_query_length: int
    max_path_steps: int
    max_alternatives: int
    max_page_size: int


class Config(ApiModel):
    """GetConfig: feature flags and limits for the client."""

    flags: dict[str, bool]
    limits: Limits
    graph_version: str | None = None


class Health(ApiModel):
    """Liveness and readiness."""

    status: str
    catalog_loaded: bool


# ---------------------------------------------------------------------------
# Errors (AIP-193)
# ---------------------------------------------------------------------------


class ErrorInfo(BaseModel):
    """google.rpc.ErrorInfo: the machine-readable cause."""

    model_config = ConfigDict(populate_by_name=True, frozen=True)

    type_: str = Field(alias="@type", examples=["type.googleapis.com/google.rpc.ErrorInfo"])
    reason: str = Field(examples=["ARTIST_NOT_FOUND"])
    domain: str = Field(examples=["songnexus.app"])
    metadata: dict[str, str]


class Status(ApiModel):
    """google.rpc.Status, as JSON."""

    code: int = Field(description="HTTP status code.", examples=[404])
    status: str = Field(description="Canonical status name.", examples=["NOT_FOUND"])
    message: str = Field(description="Developer-facing English; not for display.")
    details: list[ErrorInfo]


class ErrorResponse(ApiModel):
    """The body of every error response."""

    error: Status


# ---------------------------------------------------------------------------
# Identity and user data (M4)
# ---------------------------------------------------------------------------


class CreateSessionRequest(ApiModel):
    """CreateSession: exchange a Firebase ID token for a session cookie."""

    id_token: str = Field(min_length=1, max_length=8192)
    age_confirmed: bool = Field(
        default=False, description="Required (true) when creating an account: the user is 13+."
    )


class SessionInfo(ApiModel):
    """The current session. The cookie itself is never readable by scripts."""

    user: str = Field(description="Resource name `users/{user}`.")
    csrf_token: str = Field(description="Send as `X-CSRF-Token` on every write.")
    new_user: bool = False


class User(ApiModel):
    """GetUser. Email and name stay with the identity provider."""

    name: str
    create_time: str


class Theme(enum.StrEnum):
    """Color theme."""

    SYSTEM = "SYSTEM"
    LIGHT = "LIGHT"
    DARK = "DARK"


class Preferences(ApiModel):
    """GetPreferences / UpdatePreferences (AIP-134 update mask, AIP-154 ETag)."""

    name: str = ""
    genres: list[str] = Field(default_factory=list, max_length=20)
    categories: list[ConnectionCategory] = Field(default_factory=list)
    theme: Theme = Theme.SYSTEM
    etag: str = ""
    update_time: str | None = None


class BlockedArtist(ApiModel):
    """An artist the user never wants to see in lists or paths."""

    name: str = Field(description="`users/{user}/blockedArtists/{artist}`.")
    artist: ArtistSummary | None = Field(description="Null when the artist left the catalog.")
    create_time: str


class CreateBlockedArtistRequest(ApiModel):
    """CreateBlockedArtist."""

    artist: str = Field(description="Resource name `artists/{artist}` to block.")


class ListBlockedArtistsResponse(ApiModel):
    """ListBlockedArtists."""

    blocked_artists: list[BlockedArtist]
    next_page_token: str = ""
    total_size: int


class Visibility(enum.StrEnum):
    """Who can see a profile. Only PRIVATE exists in R1."""

    PRIVATE = "PRIVATE"


class Profile(ApiModel):
    """GetProfile / UpdateProfile: Top 5 artists (US-09)."""

    name: str = ""
    top_artists: list[str] = Field(default_factory=list, description="Up to 5 `artists/{artist}`.")
    visibility: Visibility = Visibility.PRIVATE
    etag: str = ""
    update_time: str | None = None


class Empty(ApiModel):
    """An empty response."""


# ---------------------------------------------------------------------------
# Playlist analysis (US-10)
# ---------------------------------------------------------------------------


class PlaylistTrack(ApiModel):
    """A track as the device parsed it: a title and its artist names, nothing else."""

    title: str = Field(default="", max_length=300)
    artists: list[str] = Field(
        min_length=1,
        max_length=10,
        description="Artist names as written, or `artists/{artist}` for a choice the user made.",
    )


class AnalyzePlaylistRequest(ApiModel):
    """AnalyzePlaylist. Raw files never leave the device; only names and titles are sent."""

    tracks: list[PlaylistTrack] = Field(min_length=1, max_length=10_000)
    categories: list[ConnectionCategory] = Field(default_factory=list)


class MatchStatus(enum.StrEnum):
    """How an artist name from the playlist was matched."""

    MATCHED = "MATCHED"
    AMBIGUOUS = "AMBIGUOUS"
    NO_MATCH = "NO_MATCH"


class PlaylistArtist(ApiModel):
    """One distinct artist name from the playlist and what it matched."""

    query: str
    track_count: int
    status: MatchStatus
    artist: ArtistSummary | None = None
    candidates: list[ArtistSummary] = Field(
        default_factory=list, description="For AMBIGUOUS: who it might be, best first."
    )
    blocked: bool = False


class Cohesion(ApiModel):
    """The share of matched artist pairs within 2 steps of each other."""

    score: float | None = Field(description="Null with fewer than two matched artists.")
    pairs_within_two: int
    pairs: int


class PlaylistConnector(ApiModel):
    """A hidden link: an artist outside the playlist connected to several in it."""

    artist: ArtistSummary
    linked_to: list[str] = Field(description="Resource names of the playlist artists it links.")
    score: float


class PlaylistLink(ApiModel):
    """A direct connection between two playlist artists."""

    artist_a: str
    artist_b: str
    strength: float


class PlaylistThread(ApiModel):
    """Shortest paths between consecutive playlist artists, joined."""

    artists: list[ArtistSummary]
    breaks: int = Field(description="Consecutive pairs with no path within the step limit.")


class AnalyzePlaylistResponse(ApiModel):
    """AnalyzePlaylist."""

    artists: list[PlaylistArtist]
    cohesion: Cohesion
    connectors: list[PlaylistConnector]
    links: list[PlaylistLink]
    thread: PlaylistThread
    graph_version: str


# ---------------------------------------------------------------------------
# Play: the daily puzzle (US-04)
# ---------------------------------------------------------------------------


class Puzzle(ApiModel):
    """GetDailyPuzzle: the same puzzle for every player on a date."""

    name: str = Field(description="`puzzles/{date}`, the player's local date (YYYY-MM-DD).")
    number: int = Field(description="1 on the launch day.")
    date: str
    start: ArtistSummary
    target: ArtistSummary
    par: int = Field(description="Steps in the shortest connection (3 or 4).")
    graph_version: str


class CheckMoveRequest(ApiModel):
    """CheckMove: is ``to`` directly connected to ``from``?"""

    from_artist: str = Field(description="Resource name of the current artist.")
    to_artist: str = Field(description="Resource name of the artist the player named.")


class CheckMoveResponse(ApiModel):
    """A correct move shows its evidence and the steps left; a wrong move reveals nothing."""

    connected: bool
    artist: ArtistSummary | None = None
    evidence: list[Evidence] = Field(default_factory=list)
    steps_to_target: int | None = Field(
        default=None, description="Steps left after this move; null if far or unreachable."
    )
    reached_target: bool = False


class HintRequest(ApiModel):
    """GetHint."""

    from_artist: str


class HintResponse(ApiModel):
    """Three connections of the current artist, at least one closer to the target."""

    candidates: list[ArtistSummary]


class RevealResponse(ApiModel):
    """RevealPuzzle: a shortest solution, with evidence for every step."""

    steps: list[PathStep]
    graph_version: str
