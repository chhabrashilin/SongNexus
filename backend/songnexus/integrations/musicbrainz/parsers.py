"""Validation of raw MusicBrainz JSON into typed models.

Only the fields the pipeline uses are modelled; everything else is ignored.
A record that fails validation is rejected (and counted) rather than crashing
the run, so one malformed upstream response cannot block ingestion.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field


class _MB(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True, frozen=True)


class ArtistRef(_MB):
    id: str
    name: str
    sort_name: str | None = Field(default=None, alias="sort-name")
    type: str | None = None
    country: str | None = None
    disambiguation: str | None = None


class ArtistCreditEntry(_MB):
    name: str
    joinphrase: str = ""
    artist: ArtistRef


class LifeSpan(_MB):
    begin: str | None = None
    end: str | None = None


class Alias(_MB):
    name: str
    type: str | None = None
    locale: str | None = None


class GenreTag(_MB):
    name: str
    count: int = 0


class UrlRef(_MB):
    resource: str


class Relation(_MB):
    type: str
    direction: str | None = None
    target_type: str | None = Field(default=None, alias="target-type")
    artist: ArtistRef | None = None
    url: UrlRef | None = None
    attributes: list[str] = Field(default_factory=list)
    begin: str | None = None
    end: str | None = None


class Artist(ArtistRef):
    life_span: LifeSpan | None = Field(default=None, alias="life-span")
    aliases: list[Alias] = Field(default_factory=list)
    genres: list[GenreTag] = Field(default_factory=list)
    relations: list[Relation] = Field(default_factory=list)


class Recording(_MB):
    id: str
    title: str
    length: int | None = None
    first_release_date: str | None = Field(default=None, alias="first-release-date")
    artist_credit: list[ArtistCreditEntry] = Field(default_factory=list, alias="artist-credit")
    relations: list[Relation] = Field(default_factory=list)


class Track(_MB):
    id: str
    position: int
    title: str
    recording: Recording


class Medium(_MB):
    position: int = 1
    tracks: list[Track] = Field(default_factory=list)


class ReleaseGroup(_MB):
    id: str
    title: str
    primary_type: str | None = Field(default=None, alias="primary-type")
    first_release_date: str | None = Field(default=None, alias="first-release-date")


class Release(_MB):
    id: str
    title: str
    date: str | None = None
    artist_credit: list[ArtistCreditEntry] = Field(default_factory=list, alias="artist-credit")
    release_group: ReleaseGroup = Field(alias="release-group")
    media: list[Medium] = Field(default_factory=list)
    relations: list[Relation] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Interpretation helpers
# ---------------------------------------------------------------------------

_FEATURING = re.compile(r"\b(feat|ft|featuring|with)\b\.?", re.IGNORECASE)


def split_artist_credit(credit: list[ArtistCreditEntry]) -> list[tuple[ArtistCreditEntry, str]]:
    """Assign ``primary`` or ``featured`` to each artist in an artist credit.

    MusicBrainz encodes "A & B feat. C" as entries with join phrases. Every
    artist after the first featuring join phrase is featured; artists joined
    by "&", ",", "x", "and" before that are co-primary.
    """
    roles: list[tuple[ArtistCreditEntry, str]] = []
    featuring = False
    for entry in credit:
        roles.append((entry, "featured" if featuring else "primary"))
        if _FEATURING.search(entry.joinphrase):
            featuring = True
    return roles


# Recording/release-level artist relation type -> canonical credit role.
# Anything unmapped is ignored and counted in ingestion stats.
CREDIT_ROLE_BY_RELATION: dict[str, str] = {
    "producer": "producer",
    "vocal": "vocal",
    "instrument": "instrument",
    "performer": "performer",
    "performing orchestra": "performer",
    "programming": "programming",
    "arranger": "arranger",
    "orchestrator": "arranger",
    "instrument arranger": "arranger",
    "vocal arranger": "arranger",
    "conductor": "conductor",
    "remixer": "remixer",
    "samples from artist": "sampled",
    "mix": "engineer",
    "recording": "engineer",
    "engineer": "engineer",
    "audio": "engineer",
    "sound": "engineer",
    "mastering": "engineer",
}

# Artist-to-artist relation type -> canonical relationship type.
# Personal-life relations (marriage, siblings, ...) are deliberately excluded:
# they are not musical connections. See docs/data-model.md.
ARTIST_REL_TYPE: dict[str, str] = {
    "member of band": "member_of",
    "collaboration": "collaboration",
    "is person": "is_person",
    "subgroup": "subgroup",
    "supporting musician": "supporting_musician",
    "vocal supporting musician": "supporting_musician",
    "instrumental supporting musician": "supporting_musician",
    "teacher": "teacher",
}

LINK_TYPES = {
    "discogs",
    "wikidata",
    "allmusic",
    "official homepage",
    "free streaming",
    "streaming",
    "bandcamp",
    "soundcloud",
    "youtube",
    "last.fm",
    "songkick",
}
