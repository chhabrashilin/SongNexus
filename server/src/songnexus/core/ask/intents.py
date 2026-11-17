"""The closed set of things a question can ask, shared by the parser and the model."""

from __future__ import annotations

import enum
from dataclasses import dataclass

from songnexus.core.graph.collaborations import CollaborationType, ProductionDirection

MAX_MENTION_LENGTH = 80
PAIR = 2


class Intent(enum.StrEnum):
    """What a question asks for."""

    FIND_PATH = "FIND_PATH"  # how two artists connect
    COMPARE_ARTISTS = "COMPARE_ARTISTS"
    COMPARE_SONGS = "COMPARE_SONGS"
    SONG_CREDITS = "SONG_CREDITS"  # who produced / is featured on / is credited on a song
    COLLABORATORS = "COLLABORATORS"  # an artist's collaborators, optionally narrowed
    CONNECTIONS = "CONNECTIONS"  # "artists like X", "connected to X": the connection web
    LOOKUP = "LOOKUP"  # a plain search
    UNKNOWN = "UNKNOWN"  # not something we can answer from our data


class CreditRole(enum.StrEnum):
    """Which credits of a song a question asks about."""

    PRODUCER = "PRODUCER"
    FEATURED = "FEATURED"
    PERFORMER = "PERFORMER"  # the primary artists
    ALL = "ALL"


class Source(enum.StrEnum):
    """Who interpreted the question."""

    PARSER = "PARSER"
    MODEL = "MODEL"


@dataclass(frozen=True)
class SongRef:
    """A song as named in a question: a title and, optionally, its artist."""

    title: str
    artist: str | None = None


@dataclass(frozen=True)
class Interpretation:
    """One question, as an intent with entity names (never resolved IDs, never facts).

    Attributes:
        intent: What is asked.
        artists: Artist names as written (two for a path or comparison, one otherwise).
        songs: Songs as written (two for a comparison, one for credits).
        credit_role: For song credits, which credits.
        collaboration_type: For collaborators, which kind (None: every kind).
        direction: For production collaborators, who produced whom.
        start_year: Only collaborations from this year on.
        end_year: Only collaborations up to this year.
        genre: A genre name to narrow collaborators to.
        strongest: For a path, prefer the strongest links over the fewest steps.
        text: For a lookup, what to search for.
        source: Who produced this interpretation.
    """

    intent: Intent
    artists: tuple[str, ...] = ()
    songs: tuple[SongRef, ...] = ()
    credit_role: CreditRole | None = None
    collaboration_type: CollaborationType | None = None
    direction: ProductionDirection | None = None
    start_year: int | None = None
    end_year: int | None = None
    genre: str | None = None
    strongest: bool = False
    text: str | None = None
    source: Source = Source.PARSER

    def is_complete(self) -> bool:
        """Returns whether the intent has every entity it needs."""
        needs = {
            Intent.FIND_PATH: len(self.artists) == PAIR,
            Intent.COMPARE_ARTISTS: len(self.artists) == PAIR,
            Intent.COMPARE_SONGS: len(self.songs) == PAIR,
            Intent.SONG_CREDITS: len(self.songs) == 1,
            Intent.COLLABORATORS: len(self.artists) == 1,
            Intent.CONNECTIONS: len(self.artists) == 1,
            Intent.LOOKUP: bool(self.text),
            Intent.UNKNOWN: True,
        }
        return needs[self.intent]
