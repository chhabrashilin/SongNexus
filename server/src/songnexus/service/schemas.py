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


class ProductionDirection(enum.StrEnum):
    """Who produced whom, from the requested artist's side."""

    PRODUCED_FOR = "PRODUCED_FOR"
    PRODUCED_BY = "PRODUCED_BY"
    CO_PRODUCED = "CO_PRODUCED"


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
    share: float = Field(description="Averaged over the sources with genre data for the artist.")
    sources: list[str] = Field(
        default_factory=list, description="Data sources asserting it, `dataSources/{source}`."
    )


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


class ArtistLabel(ApiModel):
    """A label an artist released on."""

    label: str = Field(description="Resource name `labels/{label}`.")
    display_name: str
    release_count: int
    first_year: int | None = None
    last_year: int | None = None


class CoListener(ApiModel):
    """An artist often played with another, by rank (ListenBrainz)."""

    artist: ArtistSummary
    rank: int


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
    labels: list[ArtistLabel] = Field(
        default_factory=list, description="Labels the artist's releases in our data came out on."
    )
    often_played_with: list[CoListener] = Field(
        default_factory=list,
        description="Catalog artists ListenBrainz listeners most often play with this one.",
    )
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
    directions: list[ProductionDirection] = Field(
        default_factory=list, description="For PRODUCTION: which ways it went; empty otherwise."
    )


class CollaborationOrder(enum.StrEnum):
    """How collaborators are listed."""

    COUNT = "COUNT"
    FIRST_YEAR = "FIRST_YEAR"


class TimelineYear(ApiModel):
    """Distinct collaborative recordings and releases in one year, by type."""

    year: int
    counts: dict[CollaborationType, int]


class ListArtistCollaborationsResponse(ApiModel):
    """ListArtistCollaborations. Counts are based on releases in our data."""

    collaborations: list[Collaboration]
    counts: dict[CollaborationType, int]
    timeline: list[TimelineYear] = Field(
        default_factory=list,
        description="Every type, the genre filter applied, the year range not applied.",
    )
    undated: dict[CollaborationType, int] = Field(
        default_factory=dict, description="Subjects with no known year, by type."
    )
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


class OverlapStrength(enum.StrEnum):
    """How strongly two audiences overlap (``core.listening``)."""

    STRONG = "STRONG"
    MODERATE = "MODERATE"
    WEAK = "WEAK"
    NONE = "NONE"


class ListenerOverlap(ApiModel):
    """Shared audience, from aggregate ListenBrainz data; never about individual listeners."""

    listeners_a: int
    listeners_b: int
    listens_a: int
    listens_b: int
    rank_b_for_a: int | None = Field(
        default=None,
        description="B's rank among the artists A's listeners most often also play (1 = most).",
    )
    rank_a_for_b: int | None = None
    strength: OverlapStrength = Field(
        description="From the better rank: STRONG <= 10, MODERATE <= 50, WEAK <= 100, else NONE."
    )
    source: SourceLink


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
    listening: ListenerOverlap | None = Field(
        default=None,
        description="Null when either artist has fewer than 50 listeners or no data.",
    )
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


class AudioDescriptors(ApiModel):
    """What AcousticBrainz measured for a recording (CC0). Any field may be missing."""

    bpm: float | None = None
    key: str | None = Field(default=None, description="Tonic, e.g. `C#`.")
    scale: str | None = Field(default=None, description="`major` or `minor`.")
    key_strength: float | None = None
    length_s: float | None = None
    average_loudness: float | None = Field(default=None, description="In [0, 1].")
    dynamic_complexity: float | None = Field(default=None, description="In dB.")
    moods: dict[str, float] = Field(
        default_factory=dict,
        description="Probability of each class: danceable, acoustic, aggressive, electronic, "
        "happy, party, relaxed, sad, instrumental, bright.",
    )
    source: SourceLink


class Recording(ApiModel):
    """GetRecording."""

    name: str
    display_name: str
    length_ms: int | None = None
    first_release_date: str | None = None
    credits: list[Credit]
    appearances: list[Appearance]
    descriptors: AudioDescriptors | None = Field(
        default=None, description="Absent when AcousticBrainz has no data for the recording."
    )
    sources: list[SourceLink]


class RecordingSummary(ApiModel):
    """A recording as shown in a comparison."""

    name: str
    display_name: str
    artists: list[ArtistSummary] = Field(description="Primary artists.")
    first_release_date: str | None = None
    length_ms: int | None = None


class SimilarityPart(ApiModel):
    """One named part of the similarity score."""

    name: str = Field(description="`mood`, `tempo`, `key` or `energy`.")
    similarity: float
    weight: float = Field(description="Its weight among the parts present; they sum to 1.")
    contribution: float = Field(description="similarity x weight: what it adds to the score.")


class SharedCredit(ApiModel):
    """A credit role compared across the two songs."""

    role: str
    both: list[ArtistSummary]
    only_a: list[ArtistSummary]
    only_b: list[ArtistSummary]


class CompareRecordingsResponse(ApiModel):
    """CompareRecordings: structure side by side, an explained similarity, shared credits."""

    recording_a: RecordingSummary
    recording_b: RecordingSummary
    descriptors_a: AudioDescriptors | None = None
    descriptors_b: AudioDescriptors | None = None
    similarity: float | None = Field(
        default=None, description="Weighted mean of the parts; null when neither song has data."
    )
    parts: list[SimilarityPart]
    shared_credits: list[SharedCredit] = Field(description="Roles with someone in common first.")
    artist_path: list[ArtistSummary] = Field(
        description="Fewest-steps path between the songs' first primary artists; empty when "
        "they are the same artist or not connected in our data."
    )
    graph_version: str


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
    artist_count: int = Field(description="Artists carrying this genre.")
    artist_count_with_subgenres: int = Field(
        description="Artists carrying this genre or any genre below it."
    )
    parents: list[str] = Field(
        default_factory=list, description="Direct parent genres, `genres/{genre}`."
    )


class ListGenresResponse(ApiModel):
    """ListGenres."""

    genres: list[Genre]
    next_page_token: str = ""
    total_size: int


class LabelArtist(ApiModel):
    """An artist on a label's roster, with when they released there."""

    artist: ArtistSummary
    release_count: int
    first_year: int | None = None
    last_year: int | None = None


class LabelRelease(ApiModel):
    """A release on a label."""

    release: str = Field(description="Resource name `releases/{release}`.")
    display_name: str
    year: int | None = None
    catalog_numbers: list[str]
    artists: list[ArtistSummary]


class Label(ApiModel):
    """GetLabel: a record label, its roster by era, and its releases in our data."""

    name: str = Field(description="Resource name `labels/{label}`.")
    display_name: str
    label_type: str | None = None
    disambiguation: str | None = None
    artists: list[LabelArtist] = Field(description="Roster, by first release year.")
    releases: list[LabelRelease] = Field(description="Releases, oldest first.")
    sources: list[SourceLink]
    graph_version: str


class ListeningProvider(enum.StrEnum):
    """A listening service (ADR 0006)."""

    LISTENBRAINZ = "LISTENBRAINZ"
    LASTFM = "LASTFM"
    LIBREFM = "LIBREFM"
    SPOTIFY = "SPOTIFY"
    DEEZER = "DEEZER"
    APPLE_MUSIC = "APPLE_MUSIC"
    YOUTUBE_MUSIC = "YOUTUBE_MUSIC"


class LinkMethod(enum.StrEnum):
    """How a provider is linked."""

    REDIRECT = "REDIRECT"
    TOKEN = "TOKEN"  # noqa: S105 - a method name, not a secret
    MUSICKIT = "MUSICKIT"
    FILE = "FILE"


class LinkedAccountStatus(enum.StrEnum):
    """Whether sync works."""

    ACTIVE = "ACTIVE"
    NEEDS_RELINK = "NEEDS_RELINK"


class LinkedAccount(ApiModel):
    """A linked listening account. Tokens are never returned."""

    name: str = Field(description="`users/{user}/linkedAccounts/{provider}`.")
    provider: ListeningProvider
    external_user: str = Field(description="The account name on the provider.")
    status: LinkedAccountStatus
    link_time: str
    last_sync_time: str | None = None
    next_sync_time: str | None = None
    unmatched_plays: int = Field(
        description="Plays whose artist could not be matched to the catalog (counted, not kept)."
    )


class ProviderOffer(ApiModel):
    """A provider as offered to the listener."""

    provider: ListeningProvider
    method: LinkMethod
    available: bool
    unavailable_reason: str = ""
    linked_account: LinkedAccount | None = None


class ListLinkedAccountsResponse(ApiModel):
    """ListLinkedAccounts: every provider, linked or not."""

    providers: list[ProviderOffer]
    sync_interval_minutes: int


class StartLinkRequest(ApiModel):
    """StartLink."""

    provider: ListeningProvider


class StartLinkResponse(ApiModel):
    """Where to send the listener to approve the link."""

    authorization_url: str


class CreateLinkedAccountRequest(ApiModel):
    """CreateLinkedAccount: a ListenBrainz user token, or an Apple Music user token."""

    provider: ListeningProvider
    token: str = Field(min_length=1, max_length=4096)


class SyncLinkedAccountResponse(ApiModel):
    """SyncLinkedAccount: what this sync read."""

    linked_account: LinkedAccount
    synced: bool = Field(
        description="False when the provider could not be read; the account's status says why."
    )
    plays: int
    artists: int
    unmatched_plays: int


class ListeningArtist(ApiModel):
    """An artist the listener played, from linked accounts."""

    artist: ArtistSummary
    plays: int
    last_play_time: str | None = None
    providers: list[ListeningProvider]


class ListListeningResponse(ApiModel):
    """ListListening: the listener's artists from linked accounts, most played first."""

    artists: list[ListeningArtist]
    next_page_token: str = ""
    total_size: int


class LicenseTier(enum.StrEnum):
    """What a data source's license allows (ADR 0005)."""

    PRODUCTION = "PRODUCTION"
    NON_COMMERCIAL = "NON_COMMERCIAL"
    EVALUATION = "EVALUATION"


class SourceStatus(enum.StrEnum):
    """Whether SongNexus reads from the source yet."""

    IN_USE = "IN_USE"
    PLANNED = "PLANNED"


class SourceKind(enum.StrEnum):
    """How the data is obtained."""

    API = "API"
    DATA_DUMP = "DATA_DUMP"
    DATASET = "DATASET"
    USER_ACCOUNT = "USER_ACCOUNT"


class DataSource(ApiModel):
    """A provider of data, with its license and what it feeds."""

    name: str = Field(description="Resource name, `dataSources/{source}`.")
    display_name: str
    homepage: str
    license: str
    license_url: str
    tier: LicenseTier
    status: SourceStatus
    kind: SourceKind
    feeds: list[str]
    attribution: str
    checked_on: str = Field(description="ISO date the license was last checked.")
    notes: str


class ListDataSourcesResponse(ApiModel):
    """ListDataSources."""

    data_sources: list[DataSource]
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


class CreateLocalSessionRequest(ApiModel):
    """CreateLocalSession (development only): sign in as a named local listener."""

    listener: str = Field(default="listener", pattern=r"^[a-z0-9-]{1,32}$")
    age_confirmed: bool = False


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


# ---------------------------------------------------------------------------
# Friends and sharing (R2-7, ADR 0007)
# ---------------------------------------------------------------------------


class ShareKind(enum.StrEnum):
    """What a share points at; decides how many subjects it has and of which type."""

    ARTIST = "ARTIST"  # one artist
    RECORDING = "RECORDING"  # one recording
    ARTIST_COMPARISON = "ARTIST_COMPARISON"  # two artists
    RECORDING_COMPARISON = "RECORDING_COMPARISON"  # two recordings
    PATH = "PATH"  # two artists: how they connect


class ReportReason(enum.StrEnum):
    """Why someone reported a share or a person."""

    SPAM = "SPAM"
    HARASSMENT = "HARASSMENT"
    HATE = "HATE"
    SEXUAL_CONTENT = "SEXUAL_CONTENT"
    OTHER = "OTHER"


class SocialProfile(ApiModel):
    """The name a user shows to friends. Friends see nothing else about each other."""

    name: str = Field(description="`users/{user}/socialProfile`.")
    display_name: str = Field(default="", max_length=40)


class UpdateSocialProfileRequest(ApiModel):
    """UpdateSocialProfile: pick the name friends see."""

    display_name: str = Field(min_length=1, max_length=40)


class Person(ApiModel):
    """Someone in the friends graph, as another user sees them."""

    user: str = Field(description="Resource name `users/{user}` (opaque).")
    display_name: str


class FriendInvite(ApiModel):
    """An invite code. The code is returned once, at creation; only its hash is stored."""

    name: str = Field(description="`users/{user}/friendInvites/{invite}`.")
    code: str = Field(default="", description="`XXXXX-XXXXX`; only in CreateFriendInvite.")
    create_time: str
    expire_time: str


class ListFriendInvitesResponse(ApiModel):
    """ListFriendInvites: the user's unexpired invites, newest first (codes not included)."""

    friend_invites: list[FriendInvite]


class FriendInvitePreview(ApiModel):
    """GetFriendInvite: who an invite is from, before accepting it."""

    inviter: Person
    expire_time: str
    already_friends: bool = False


class Friend(ApiModel):
    """A friend."""

    name: str = Field(description="`users/{user}/friends/{friend}`.")
    person: Person
    create_time: str


class ListFriendsResponse(ApiModel):
    """ListFriends: oldest friendship first."""

    friends: list[Friend]
    next_page_token: str = ""
    total_size: int


class BlockedUser(ApiModel):
    """A person the user blocked. Blocks are silent and hide both people from each other."""

    name: str = Field(description="`users/{user}/blockedUsers/{blocked}`.")
    person: Person
    create_time: str


class CreateBlockedUserRequest(ApiModel):
    """CreateBlockedUser: a friend, or someone who shared with you."""

    user: str = Field(description="Resource name `users/{user}`.")


class ListBlockedUsersResponse(ApiModel):
    """ListBlockedUsers: oldest first."""

    blocked_users: list[BlockedUser]


class SharedSubject(ApiModel):
    """An artist or recording in a share, resolved against the current catalog."""

    name: str = Field(description="`artists/{artist}` or `recordings/{recording}`.")
    display_name: str = Field(description="Empty when the catalog no longer has it.")
    available: bool


class Share(ApiModel):
    """Something one friend sent another."""

    name: str = Field(description="`shares/{share}`.")
    sender: Person
    recipient: Person
    kind: ShareKind
    subjects: list[SharedSubject]
    note: str = ""
    create_time: str
    read: bool = False


class CreateShareRequest(ApiModel):
    """CreateShare: send an artist, song, comparison or path to a friend."""

    recipient: str = Field(description="A friend, `users/{user}`.")
    kind: ShareKind
    subjects: list[str] = Field(min_length=1, max_length=2)
    note: str = Field(default="", max_length=140)


class ListInboxResponse(ApiModel):
    """ListInbox: shares received, newest first."""

    shares: list[Share]
    next_page_token: str = ""
    total_size: int
    unread_count: int


class MarkAllReadResponse(ApiModel):
    """MarkInboxRead: how many shares were marked read."""

    marked: int


class CreateReportRequest(ApiModel):
    """CreateReport: report a share you received, or a person you know. Give one of the two."""

    share: str = Field(default="", description="`shares/{share}` you received.")
    user: str = Field(default="", description="`users/{user}`: a friend or someone who shared.")
    reason: ReportReason
    details: str = Field(default="", max_length=500)


class Report(ApiModel):
    """A filed report. Moderators review it; the reporter sees only that it was received."""

    name: str = Field(description="`reports/{report}`.")
    reason: ReportReason
    create_time: str
