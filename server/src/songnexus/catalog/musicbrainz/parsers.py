"""Validation of raw MusicBrainz JSON into typed models, and its interpretation.

Only fields the pipeline uses are modelled; the rest is ignored. A record that
fails validation is rejected and counted by the caller, so one malformed
upstream response cannot block ingestion.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field

from songnexus.core.model import CreditRole, RelationType


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True, frozen=True)


class ArtistRef(_Model):
    """An artist as referenced from another entity (credit or relationship)."""

    id: str
    name: str
    sort_name: str | None = Field(default=None, alias="sort-name")
    type: str | None = None
    country: str | None = None
    disambiguation: str | None = None


class ArtistCreditEntry(_Model):
    """One artist in an artist credit, with the text that joins it to the next."""

    name: str
    joinphrase: str = ""
    artist: ArtistRef


class LifeSpan(_Model):
    """Begin and end dates of an artist, as partial ISO dates."""

    begin: str | None = None
    end: str | None = None


class Alias(_Model):
    """An alternative name (other scripts, legal name, search hint)."""

    name: str
    type: str | None = None
    locale: str | None = None


class GenreTag(_Model):
    """A genre associated with an artist and its vote count (CC BY-NC-SA, ADR 0003)."""

    name: str
    count: int = 0


class UrlRef(_Model):
    """A URL relationship target."""

    resource: str


class Relation(_Model):
    """A relationship from the looked-up entity to an artist or URL."""

    type: str
    direction: str | None = None
    target_type: str | None = Field(default=None, alias="target-type")
    artist: ArtistRef | None = None
    url: UrlRef | None = None
    attributes: list[str] = Field(default_factory=list)
    begin: str | None = None
    end: str | None = None


class Artist(ArtistRef):
    """An artist lookup: identity plus aliases, genres and relationships."""

    life_span: LifeSpan | None = Field(default=None, alias="life-span")
    aliases: list[Alias] = Field(default_factory=list)
    genres: list[GenreTag] = Field(default_factory=list)
    relations: list[Relation] = Field(default_factory=list)


class Recording(_Model):
    """A recorded performance with its artist credit and recording-level credits."""

    id: str
    title: str
    length: int | None = None
    first_release_date: str | None = Field(default=None, alias="first-release-date")
    artist_credit: list[ArtistCreditEntry] = Field(default_factory=list, alias="artist-credit")
    relations: list[Relation] = Field(default_factory=list)


class Track(_Model):
    """A recording's position on a medium."""

    id: str
    position: int
    title: str
    recording: Recording


class Medium(_Model):
    """One disc or side of a release."""

    position: int = 1
    tracks: list[Track] = Field(default_factory=list)


class ReleaseGroup(_Model):
    """The album-level grouping of releases (what listeners call "an album")."""

    id: str
    title: str
    primary_type: str | None = Field(default=None, alias="primary-type")
    first_release_date: str | None = Field(default=None, alias="first-release-date")


class LabelRef(_Model):
    """A record label."""

    id: str
    name: str
    type: str | None = None
    disambiguation: str | None = None


class LabelInfo(_Model):
    """A label credit on a release, with its catalog number."""

    catalog_number: str | None = Field(default=None, alias="catalog-number")
    label: LabelRef | None = None


class Release(_Model):
    """A release lookup: tracklist, credits, relationships and labels."""

    id: str
    title: str
    date: str | None = None
    artist_credit: list[ArtistCreditEntry] = Field(default_factory=list, alias="artist-credit")
    release_group: ReleaseGroup = Field(alias="release-group")
    media: list[Medium] = Field(default_factory=list)
    relations: list[Relation] = Field(default_factory=list)
    label_info: list[LabelInfo] = Field(default_factory=list, alias="label-info")


# ---------------------------------------------------------------------------
# Interpretation
# ---------------------------------------------------------------------------

_FEATURING = re.compile(r"\b(feat|ft|featuring|with)\b\.?", re.IGNORECASE)


def split_artist_credit(
    credit: list[ArtistCreditEntry],
) -> list[tuple[ArtistCreditEntry, CreditRole]]:
    """Assigns primary or featured to each artist in an artist credit.

    MusicBrainz encodes "A & B feat. C" as entries with join phrases. Everyone
    after the first featuring join phrase is featured; artists joined by "&",
    ",", "x" or "and" before it are co-primary.
    """
    roles: list[tuple[ArtistCreditEntry, CreditRole]] = []
    featuring = False
    for entry in credit:
        roles.append((entry, CreditRole.FEATURED if featuring else CreditRole.PRIMARY))
        if _FEATURING.search(entry.joinphrase):
            featuring = True
    return roles


# Recording- and release-level artist relationship -> credit role. Unmapped types
# are ignored and counted in ingestion statistics, never guessed.
CREDIT_ROLE_BY_RELATION: dict[str, CreditRole] = {
    "producer": CreditRole.PRODUCER,
    "vocal": CreditRole.VOCAL,
    "instrument": CreditRole.INSTRUMENT,
    "performer": CreditRole.PERFORMER,
    "performing orchestra": CreditRole.PERFORMER,
    "programming": CreditRole.PROGRAMMING,
    "arranger": CreditRole.ARRANGER,
    "orchestrator": CreditRole.ARRANGER,
    "instrument arranger": CreditRole.ARRANGER,
    "vocal arranger": CreditRole.ARRANGER,
    "conductor": CreditRole.CONDUCTOR,
    "remixer": CreditRole.REMIXER,
    "samples from artist": CreditRole.SAMPLED,
    "mix": CreditRole.ENGINEER,
    "recording": CreditRole.ENGINEER,
    "engineer": CreditRole.ENGINEER,
    "audio": CreditRole.ENGINEER,
    "sound": CreditRole.ENGINEER,
    "mastering": CreditRole.ENGINEER,
}

# Artist-to-artist relationship -> canonical type. In MusicBrainz the looked-up
# artist is the relationship's subject when ``direction`` is "forward".
RELATION_TYPE_BY_NAME: dict[str, RelationType] = {
    "member of band": RelationType.MEMBER_OF,
    "subgroup": RelationType.HAS_SUBGROUP,
    "is person": RelationType.PERFORMS_AS,
    "collaboration": RelationType.COLLABORATION_IN,
    "supporting musician": RelationType.SUPPORTED,
    "vocal supporting musician": RelationType.SUPPORTED,
    "instrumental supporting musician": RelationType.SUPPORTED,
    "teacher": RelationType.TAUGHT,
}

LINK_TYPES = frozenset(
    {
        "allmusic",
        "bandcamp",
        "discogs",
        "free streaming",
        "last.fm",
        "official homepage",
        "songkick",
        "soundcloud",
        "streaming",
        "wikidata",
        "youtube",
    }
)
