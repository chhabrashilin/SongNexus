"""API schemas for Around you: communities, their charts, and the listener's memberships.

Charts carry ranks and ranges only. No schema here has a field for a member, a
member count below the chart floor other than ``listenersNeeded``, or a play count.
"""

from __future__ import annotations

import enum

from songnexus.service.schemas import ApiModel, ArtistSummary


class CommunityKind(enum.StrEnum):
    """A campus (university) or a city."""

    CAMPUS = "CAMPUS"
    CITY = "CITY"


class Community(ApiModel):
    """A campus or city listeners can join (from the curated Wikidata directory)."""

    name: str  # communities/{community}
    kind: CommunityKind
    display_name: str
    short_name: str
    city: str
    region: str  # ISO 3166-2 ("US-WI"), or ""
    country: str  # ISO 3166-1 alpha-2
    website: str  # domain, or ""
    city_community: str | None = None  # a campus's city: communities/{community}
    source_url: str  # the Wikidata item it was built from
    synthetic: bool = False


class ListCommunitiesResponse(ApiModel):
    """ListCommunities: communities matching a search, best first."""

    communities: list[Community]
    next_page_token: str = ""
    total_size: int


class ListenerRange(ApiModel):
    """A count shown as a range: ``min`` to ``max`` listeners (``max`` null: or more)."""

    min: int
    max: int | None = None


class ChartState(enum.StrEnum):
    """Whether a community has enough listeners to show its chart."""

    LOCKED = "LOCKED"
    UNLOCKED = "UNLOCKED"


class ChartMovement(enum.StrEnum):
    """An artist's movement since the chart a week earlier."""

    UP = "UP"
    DOWN = "DOWN"
    SAME = "SAME"
    NEW = "NEW"


class CommunityChartArtist(ApiModel):
    """A chart row: rank, artist, listeners as a range, movement."""

    rank: int
    artist: ArtistSummary
    listeners: ListenerRange
    movement: ChartMovement | None = None  # null until a week of history exists
    places: int = 0  # places moved, for UP and DOWN
    rising: bool = False


class CommunityChartGenre(ApiModel):
    """A genre the community listens to, with listeners as a range."""

    genre: str  # genres/{genre}
    display_name: str
    listeners: ListenerRange


class CommunityChart(ApiModel):
    """GetCommunityChart: what a community listens to, aggregated and anonymous."""

    name: str  # communities/{community}/chart
    community: Community
    state: ChartState
    listeners_needed: int  # more listeners with data needed to unlock; 0 when unlocked
    min_listeners: int  # the chart floor
    min_artist_listeners: int  # the floor for any one artist or genre row
    listeners: ListenerRange | None = None  # listeners with data, when unlocked
    artists: list[CommunityChartArtist]
    rising: list[CommunityChartArtist]
    genres: list[CommunityChartGenre]
    history_available: bool  # movement and rising need a week of history
    demo_data: bool  # synthetic development members contributed
    update_time: str
    next_update_time: str
    graph_version: str


class CommunityMembership(ApiModel):
    """A community the listener joined."""

    community: Community
    join_time: str


class UserCommunities(ApiModel):
    """GetUserCommunities: the listener's campus and city (each optional)."""

    name: str  # users/{user}/communities
    campus: CommunityMembership | None = None
    city: CommunityMembership | None = None
    has_listening_data: bool  # whether the listener's own plays can count toward charts


class UpdateUserCommunitiesRequest(ApiModel):
    """UpdateUserCommunities body: a community name to join, or "" to leave.

    Only the fields in ``updateMask`` (or, without one, the fields present) change.
    """

    campus: str = ""
    city: str = ""
