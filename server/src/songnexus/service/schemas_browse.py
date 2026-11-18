"""Schemas for browse surfaces: home shelves, genre pages, recommendations, taste profiles."""

from __future__ import annotations

import enum

from pydantic import Field

from songnexus.service.schemas import ApiModel, ArtistSummary, SourceLink

Params = dict[str, str | int]


class ShelfReasonKind(enum.StrEnum):
    """Why an item is on a shelf."""

    PRODUCED_RECORDINGS = "PRODUCED_RECORDINGS"
    COLLABORATORS = "COLLABORATORS"
    GENRES_BRIDGED = "GENRES_BRIDGED"
    RELEASED_ON_DAY = "RELEASED_ON_DAY"
    CREDITED_RECORDINGS = "CREDITED_RECORDINGS"
    LABEL_RELEASES = "LABEL_RELEASES"


class Reason(ApiModel):
    """A machine-readable reason: a kind, its client message key and the numbers behind it."""

    kind: ShelfReasonKind
    message_id: str = Field(description="Client message key, e.g. `reason.producedRecordings`.")
    params: Params = Field(default_factory=dict, description="Counts, years and roles.")


class ShelfKind(enum.StrEnum):
    """Which kind of shelf."""

    BEHIND_THE_HITS = "BEHIND_THE_HITS"
    SUPER_CONNECTORS = "SUPER_CONNECTORS"
    GENRE_BRIDGES = "GENRE_BRIDGES"
    ON_THIS_DAY = "ON_THIS_DAY"
    GENRE = "GENRE"
    DECADE = "DECADE"
    LABELS = "LABELS"


class ShelfRecording(ApiModel):
    """A recording on a shelf."""

    name: str = Field(description="`recordings/{recording}`.")
    display_name: str
    year: int | None = None
    first_release_date: str | None = None
    artists: list[ArtistSummary] = Field(description="Primary artists.")


class ShelfLabel(ApiModel):
    """A label on a shelf."""

    name: str = Field(description="`labels/{label}`.")
    display_name: str


class ShelfItem(ApiModel):
    """One shelf item: exactly one of `artist`, `recording` or `label` is set."""

    artist: ArtistSummary | None = None
    recording: ShelfRecording | None = None
    label: ShelfLabel | None = None
    reason: Reason


class Shelf(ApiModel):
    """A home shelf: a title template, its parameters and its items, best first."""

    name: str = Field(description="`shelves/{shelf}`, stable within a catalog version.")
    kind: ShelfKind
    message_id: str = Field(description="Client message key for the title, e.g. `shelf.genre`.")
    params: Params = Field(default_factory=dict, description="Title template values.")
    genre: str | None = Field(
        default=None, description="For GENRE shelves, `genres/{genre}` (the see-all page)."
    )
    items: list[ShelfItem]


class ListShelvesResponse(ApiModel):
    """ListShelves: the home page's shelves, in display order. Empty shelves are left out."""

    shelves: list[Shelf]
    graph_version: str


class GenreRef(ApiModel):
    """A related genre with its artist counts."""

    name: str = Field(description="`genres/{genre}`.")
    display_name: str
    artist_count: int
    artist_count_with_subgenres: int


class GenreDetail(ApiModel):
    """GetGenre: a genre, where it sits in the hierarchy, and how many artists it has."""

    name: str = Field(description="`genres/{genre}`.")
    display_name: str
    artist_count: int = Field(description="Artists carrying this genre.")
    artist_count_with_subgenres: int = Field(
        description="Artists carrying this genre or any genre below it."
    )
    member_count: int = Field(
        description="Artists listed by ListGenreArtists: at least 20% of their genre shares in "
        "this genre or its subgenres (the genre filter's rule)."
    )
    top_level: bool = Field(description="True when the genre has no parent.")
    parents: list[GenreRef] = Field(default_factory=list)
    children: list[GenreRef] = Field(
        default_factory=list, description="Direct subgenres with artists, most artists first."
    )
    graph_version: str


class GenreArtist(ApiModel):
    """An artist in a genre."""

    artist: ArtistSummary
    collaborator_count: int = Field(description="Distinct collaborators (as on artist pages).")
    genre_share: float = Field(description="Share of the artist's genres in this genre, 0 to 1.")


class ListGenreArtistsResponse(ApiModel):
    """ListGenreArtists: a genre's artists, most connected first."""

    artists: list[GenreArtist]
    next_page_token: str = ""
    total_size: int
    graph_version: str


class RecommendationReasonKind(enum.StrEnum):
    """Why an artist is recommended."""

    SHARED_COLLABORATORS = "SHARED_COLLABORATORS"
    LISTENERS_IN_COMMON = "LISTENERS_IN_COMMON"
    SAME_LABEL = "SAME_LABEL"


class RecommendationReason(ApiModel):
    """One checkable reason for a recommendation."""

    kind: RecommendationReasonKind
    message_id: str = Field(description="Client message key, e.g. `recommend.sharedCollaborators`.")
    params: Params = Field(default_factory=dict)
    via: list[ArtistSummary] = Field(
        default_factory=list,
        description="SHARED_COLLABORATORS: up to 3 shared collaborators, strongest links first. "
        "Each link opens as a connection.",
    )
    label: ShelfLabel | None = Field(default=None, description="SAME_LABEL: the shared label.")
    source: SourceLink | None = Field(
        default=None, description="LISTENERS_IN_COMMON: where the aggregate data comes from."
    )


class Recommendation(ApiModel):
    """A recommended artist, not directly connected to the one asked about."""

    artist: ArtistSummary
    score: float = Field(description="Ranking score (higher first); for ordering only.")
    reasons: list[RecommendationReason] = Field(description="Never empty.")


class RecommendArtistsResponse(ApiModel):
    """RecommendArtists."""

    artist: ArtistSummary
    recommendations: list[Recommendation]
    graph_version: str


class ComputeTasteProfileRequest(ApiModel):
    """ComputeTasteProfile: the artists to profile (e.g. matched from a playlist on the device)."""

    artists: list[str] = Field(
        description="Artist resource names, most important first; duplicates are ignored.",
        min_length=1,
        max_length=500,
    )


class TasteSlice(ApiModel):
    """A share of a taste breakdown."""

    share: float = Field(description="0 to 1; the shares of one breakdown sum to 1.")
    artist_count: int = Field(description="Profiled artists contributing to this slice.")


class TasteGenre(TasteSlice):
    """A top-level genre's share."""

    genre: str = Field(description="`genres/{genre}`.")
    display_name: str


class TasteDecade(TasteSlice):
    """A decade's share."""

    decade: int = Field(examples=[1990])


class TasteCentral(ApiModel):
    """The profiled artist directly connected to the most of the others."""

    artist: ArtistSummary
    linked_count: int


class TasteConnector(ApiModel):
    """An artist outside the list connected to several of its artists."""

    artist: ArtistSummary
    linked_count: int
    linked_to: list[str] = Field(description="The profiled artists it connects, `artists/{id}`.")


class TasteCluster(ApiModel):
    """The tightest group: every member is directly connected to `minLinks` others in it."""

    artists: list[ArtistSummary] = Field(description="Up to 25 members, heaviest first.")
    size: int
    min_links: int
    links: int = Field(description="Direct connections inside the group.")


class TastePair(ApiModel):
    """Two profiled artists far apart: open them with FindPath."""

    artist_a: ArtistSummary
    artist_b: ArtistSummary
    steps: int


class TasteProfile(ApiModel):
    """A taste profile, computed from the graph only. Missing parts are null or empty."""

    artist_count: int = Field(description="Artists profiled.")
    skipped_artist_count: int = Field(
        default=0,
        description="Artists left out: not in the catalog, blocked, or beyond the first 500.",
    )
    genres: list[TasteGenre] = Field(description="Top-level genres, largest share first (10 max).")
    unknown_genre_artist_count: int
    decades: list[TasteDecade] = Field(description="Oldest first.")
    undated_artist_count: int
    most_central: TasteCentral | None = None
    hidden_connectors: list[TasteConnector] = Field(default_factory=list)
    tightest_cluster: TasteCluster | None = None
    surprising_pair: TastePair | None = Field(
        default=None, description="Among the 20 heaviest artists, the farthest connected pair."
    )
    collaborators_reached: int
    graph_version: str
