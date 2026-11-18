"""Schemas for the games hub and stories (Credit check trivia and the stories feed)."""

from __future__ import annotations

import enum

from pydantic import Field

from songnexus.service.schemas import ApiModel, ArtistSummary, Evidence, SourceLink, Subject


class TriviaQuestionKind(enum.StrEnum):
    """What a Credit check question asks."""

    WHO_PRODUCED = "WHO_PRODUCED"
    WHO_FEATURED = "WHO_FEATURED"
    WORKED_WITH = "WORKED_WITH"
    WHICH_LABEL = "WHICH_LABEL"


class TriviaOption(ApiModel):
    """One answer option: an artist (`artists/{id}`) or a label (`labels/{id}`)."""

    name: str
    display_name: str
    disambiguation: str | None = None


class TriviaQuestion(ApiModel):
    """A question and its options, never its answer."""

    id: str = Field(description="`q1` to `q5`, stable within the day.", examples=["q1"])
    kind: TriviaQuestionKind
    message_id: str = Field(description="Client message key, e.g. `trivia.whoProduced`.")
    subject: Subject | None = Field(
        default=None, description="The song or release asked about; null for WORKED_WITH."
    )
    artist: ArtistSummary = Field(
        description="The artist the question is about: the song's main artist, or the artist "
        "in a WORKED_WITH question."
    )
    options: list[TriviaOption]


class TriviaQuiz(ApiModel):
    """GetTrivia: the same Credit check for every player on a date."""

    name: str = Field(description="`trivia/{date}`, the player's local date (YYYY-MM-DD).")
    number: int = Field(description="1 on the launch day.")
    date: str
    questions: list[TriviaQuestion]
    graph_version: str


class CheckTriviaRequest(ApiModel):
    """CheckTrivia: is this option the right one for the question?"""

    question: str = Field(description="The question ID, e.g. `q1`.", max_length=8)
    option: str = Field(description="The chosen option's resource name.", max_length=64)


class CheckTriviaResponse(ApiModel):
    """The verdict, the right option and the credits behind it."""

    correct: bool
    correct_option: TriviaOption
    evidence: list[Evidence] = Field(
        default_factory=list,
        description="Credits that make the right option right, with sources. Empty for "
        "WHICH_LABEL, which cites `sources` instead.",
    )
    sources: list[SourceLink] = Field(
        default_factory=list,
        description="Pages where the fact can be checked (the release and the label).",
    )
    subject: Subject | None = None


class StoryKind(enum.StrEnum):
    """Which template a story uses."""

    SHARED_PRODUCER = "SHARED_PRODUCER"
    TWO_STEPS = "TWO_STEPS"
    SESSION_PLAYER = "SESSION_PLAYER"
    LABEL_MATES = "LABEL_MATES"
    SAME_SAMPLE = "SAME_SAMPLE"
    SAMPLED = "SAMPLED"


class StoryPart(ApiModel):
    """An artist in a story, by the role the template gives it (`a`, `b`, `via`)."""

    role: str
    artist: ArtistSummary


class Story(ApiModel):
    """A generated connection story: a template, its artists and the credits that prove it."""

    name: str = Field(description="`stories/{story}`.")
    kind: StoryKind
    message_id: str = Field(description="Client message key, e.g. `story.sharedProducer`.")
    parts: list[StoryPart]
    params: dict[str, str | int] = Field(
        default_factory=dict, description="Other template values: counts, years, a title."
    )
    credits: list[Evidence] = Field(description="The strongest credit first; every one is sourced.")


class ListStoriesResponse(ApiModel):
    """ListStories: a page of the feed."""

    stories: list[Story]
    next_page_token: str = ""
    total_size: int
    graph_version: str


class PathChallenge(ApiModel):
    """GetPathChallenge: two well-known artists to connect, the same for everyone on a date."""

    name: str = Field(description="`pathChallenges/{date}`.")
    date: str
    from_artist: ArtistSummary
    to_artist: ArtistSummary
    steps: int = Field(description="Connections on a shortest path (3 to 5).")
    graph_version: str
