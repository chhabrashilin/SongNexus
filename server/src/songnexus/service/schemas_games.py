"""API schemas for game scores, leaderboards (ADR 0010), friend paths and weekly movers.

Campus leaderboards carry ranks, rounded averages and player ranges only; a
person appears only on the friends leaderboard, which only accepted friends see.
"""

from __future__ import annotations

import enum

from pydantic import Field

from songnexus.service.schemas import ApiModel, ArtistSummary, PathStep, Person
from songnexus.service.schemas_community import Community, ListenerRange


class Game(enum.StrEnum):
    """A game with a leaderboard: the daily puzzle or Credit check."""

    PUZZLE = "PUZZLE"
    TRIVIA = "TRIVIA"


class LeaderboardPeriod(enum.StrEnum):
    """One day, or the ISO week (Monday to Sunday) containing the date."""

    DAY = "DAY"
    WEEK = "WEEK"


class SubmitPuzzleScoreRequest(ApiModel):
    """SubmitPuzzleScore: the moves that solved the puzzle, start first and target last."""

    moves: list[str] = Field(
        min_length=2, max_length=21, description="`artists/{artist}` in the order played."
    )


class TriviaAnswer(ApiModel):
    """One answered Credit check question."""

    question: str = Field(max_length=8, description="Question ID, `q1` to `q5`.")
    option: str = Field(max_length=64, description="The chosen `artists/{id}` or `labels/{id}`.")


class SubmitTriviaScoreRequest(ApiModel):
    """SubmitTriviaScore: an answer to every question of the day."""

    answers: list[TriviaAnswer] = Field(min_length=1, max_length=10)


class GameScore(ApiModel):
    """A score the server computed from a submitted play (one per game per day)."""

    name: str = Field(description="`users/{user}/gameScores/{game}-{date}`.")
    game: Game
    date: str
    points: int
    max_points: int
    steps: int | None = None  # PUZZLE
    par: int | None = None  # PUZZLE
    correct: int | None = None  # TRIVIA
    total: int | None = None  # TRIVIA
    campus: str | None = Field(default=None, description="`communities/{id}` it counts for.")
    submit_time: str
    synthetic: bool = Field(default=False, description="Demo data from `songnexus seed-demo`.")


class ListGameScoresResponse(ApiModel):
    """ListGameScores: the player's own scores of the last two weeks, newest first."""

    game_scores: list[GameScore]


class CampusStanding(ApiModel):
    """A campus on the leaderboard: aggregate only."""

    rank: int
    community: Community
    players: ListenerRange
    average_points: int = Field(description="Members' average points over the period, rounded.")


class ViewerCampusState(enum.StrEnum):
    """Where the viewer's campus stands."""

    RANKED = "RANKED"
    NEEDS_PLAYERS = "NEEDS_PLAYERS"  # fewer than minPlayers members scored
    NO_CAMPUS = "NO_CAMPUS"  # the viewer has not joined a campus


class ViewerCampus(ApiModel):
    """The signed-in viewer's campus on this leaderboard."""

    state: ViewerCampusState
    community: Community | None = None
    rank: int | None = None
    players_needed: int = 0


class CampusLeaderboard(ApiModel):
    """GetCampusLeaderboard: the top campuses for a day or week."""

    name: str = Field(description="`leaderboards/campuses`.")
    game: Game
    period: LeaderboardPeriod
    start_date: str
    end_date: str
    min_players: int
    campuses: list[CampusStanding]
    ranked_campuses: int = Field(description="How many campuses met the player floor.")
    viewer_campus: ViewerCampus | None = Field(default=None, description="Signed-in only.")
    demo_data: bool = Field(default=False, description="Synthetic demo players contributed.")


class FriendStanding(ApiModel):
    """The viewer or an accepted friend on the friends leaderboard."""

    rank: int
    person: Person
    points: int
    days_played: int
    is_viewer: bool = False


class FriendLeaderboard(ApiModel):
    """GetFriendLeaderboard: the viewer and accepted friends who scored in the period."""

    name: str = Field(description="`users/{user}/friendLeaderboard`.")
    game: Game
    period: LeaderboardPeriod
    start_date: str
    end_date: str
    standings: list[FriendStanding]


class SharedCollaborator(ApiModel):
    """An artist who worked with one of your top artists and one of your friend's."""

    artist: ArtistSummary
    viewer_artists: list[str] = Field(description="Your top artists it connects to.")
    friend_artists: list[str] = Field(description="Your friend's top artists it connects to.")


class FriendPath(ApiModel):
    """A shortest connection from one of your top artists to one of your friend's."""

    from_artist: ArtistSummary
    to_artist: ArtistSummary
    steps: list[PathStep]


class FriendPaths(ApiModel):
    """GetFriendPaths: how your top artists connect to an accepted friend's."""

    name: str = Field(description="`users/{user}/friends/{friend}/paths`.")
    friend: Person
    viewer_artists: list[ArtistSummary]
    friend_artists: list[ArtistSummary]
    shared_artists: list[ArtistSummary]
    shared_collaborators: list[SharedCollaborator]
    paths: list[FriendPath]
    demo_data: bool = Field(default=False, description="The friend is a synthetic demo listener.")
    graph_version: str


class MoversState(enum.StrEnum):
    """Whether a weekly recap can be shown."""

    LOCKED = "LOCKED"  # the chart itself is locked
    NO_HISTORY = "NO_HISTORY"  # no unlocked chart from a week ago is stored yet
    AVAILABLE = "AVAILABLE"


class ChartMover(ApiModel):
    """An artist that moved. A rank is null where the artist was not on that chart."""

    artist: ArtistSummary
    rank: int | None = None
    previous_rank: int | None = None
    places: int = 0


class WeeklyMovers(ApiModel):
    """GetWeeklyMovers: the community chart's rises, falls, entries and exits this week."""

    name: str = Field(description="`communities/{community}/weeklyMovers`.")
    community: Community
    state: MoversState
    rose: list[ChartMover]
    fell: list[ChartMover]
    entered: list[ChartMover]
    left: list[ChartMover]
    update_time: str
    previous_update_time: str | None = None
    demo_data: bool = False
    graph_version: str
