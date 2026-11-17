"""Schemas for AskCatalog: a question in the search bar, answered from our data (ADR 0008)."""

from __future__ import annotations

import enum

from pydantic import Field

from songnexus.service.schemas import (
    ApiModel,
    ArtistSummary,
    CollaborationType,
    Evidence,
    ProductionDirection,
    SourceLink,
)

MAX_CHOICES = 4


class AskRequest(ApiModel):
    """AskCatalog: only the question text (and any "Did you mean" picks) is sent."""

    query: str = Field(min_length=1, max_length=120, description="The question as typed.")
    choices: list[str] = Field(
        default_factory=list,
        max_length=MAX_CHOICES,
        description="Resource names picked for ambiguous names (`artists/{id}`, "
        "`recordings/{id}`) from a previous answer's alternatives.",
    )


class AskIntent(enum.StrEnum):
    """What the question was understood to ask."""

    FIND_PATH = "FIND_PATH"
    COMPARE_ARTISTS = "COMPARE_ARTISTS"
    COMPARE_SONGS = "COMPARE_SONGS"
    SONG_CREDITS = "SONG_CREDITS"
    COLLABORATORS = "COLLABORATORS"
    CONNECTIONS = "CONNECTIONS"
    LOOKUP = "LOOKUP"
    UNKNOWN = "UNKNOWN"


class InterpretedBy(enum.StrEnum):
    """Who read the question: the built-in parser, the model, or no one (not understood)."""

    PARSER = "PARSER"
    MODEL = "MODEL"
    NONE = "NONE"


class AskCreditRole(enum.StrEnum):
    """Which credits of a song were asked about."""

    PRODUCER = "PRODUCER"
    FEATURED = "FEATURED"
    PERFORMER = "PERFORMER"
    ALL = "ALL"


class AskInterpretation(ApiModel):
    """The question as understood: an intent and its narrowing, never a fact."""

    intent: AskIntent
    interpreted_by: InterpretedBy
    credit_role: AskCreditRole | None = None
    collaboration_type: CollaborationType | None = None
    direction: ProductionDirection | None = None
    start_year: int | None = None
    end_year: int | None = None
    genre: str | None = Field(default=None, description="Resource name `genres/{genre}`.")
    genre_display_name: str | None = None
    strongest: bool = False


class EntityStatus(enum.StrEnum):
    """How a name in the question resolved."""

    MATCHED = "MATCHED"
    AMBIGUOUS = "AMBIGUOUS"
    NOT_FOUND = "NOT_FOUND"


class AskCandidate(ApiModel):
    """A catalog entity a name refers to (or might)."""

    name: str = Field(description="Resource name `artists/{id}` or `recordings/{id}`.")
    display_name: str
    subtitle: str = ""


class AskEntity(ApiModel):
    """A name from the question and what it resolved to."""

    mention: str
    entity_type: str = Field(description="`ARTIST` or `RECORDING`.")
    status: EntityStatus
    match: AskCandidate | None = None
    alternatives: list[AskCandidate] = Field(
        default_factory=list, description="Other entities with this name (ambiguous: pick one)."
    )


class AskAnswer(ApiModel):
    """The short answer as a client message: an ID and its values (lists are names)."""

    message_id: str = Field(description="Client message key, e.g. `ask.answer.path`.")
    params: dict[str, str | int | list[str]] = Field(default_factory=dict)


class AskRow(ApiModel):
    """A supporting result: an artist or a song, and why it is here."""

    artist: ArtistSummary | None = None
    recording: AskCandidate | None = None
    role: str | None = Field(default=None, description="Credit role on the song, e.g. `producer`.")
    count: int | None = Field(default=None, description="Collaborations behind it, if counted.")
    first_year: int | None = None
    last_year: int | None = None
    evidence: list[Evidence] = Field(default_factory=list)
    sources: list[SourceLink] = Field(
        default_factory=list, description="For a credit row: where the credit can be checked."
    )


class AskModelInfo(ApiModel):
    """The language model behind interpretation, for "How this answer works"."""

    configured: bool
    used: bool = Field(description="Whether the model read this question.")
    provider: str | None = None
    model: str | None = None


class AskResponse(ApiModel):
    """AskCatalog."""

    interpretation: AskInterpretation
    answer: AskAnswer
    entities: list[AskEntity]
    results: list[AskRow]
    artists: list[ArtistSummary] = Field(
        description="Every artist the answer and its evidence mention, to name them."
    )
    destination: str | None = Field(
        default=None, description="The app page with the full answer, e.g. `/compare?a=…&b=…`."
    )
    model: AskModelInfo
    graph_version: str
