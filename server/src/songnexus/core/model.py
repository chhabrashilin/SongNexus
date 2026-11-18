"""Closed vocabularies of the canonical catalog model.

Every source maps into these sets. A value outside them is a data-quality
violation, not an extension point.
"""

from __future__ import annotations

import enum


class CreditRole(enum.StrEnum):
    """An artist's role on a recording or release."""

    PRIMARY = "primary"
    FEATURED = "featured"
    PRODUCER = "producer"
    VOCAL = "vocal"
    INSTRUMENT = "instrument"
    PERFORMER = "performer"
    PROGRAMMING = "programming"
    ARRANGER = "arranger"
    CONDUCTOR = "conductor"
    REMIXER = "remixer"
    SAMPLED = "sampled"
    ENGINEER = "engineer"


PERFORMER_ROLES = frozenset({CreditRole.PRIMARY, CreditRole.FEATURED})
CONTRIBUTOR_ROLES = frozenset(
    {
        CreditRole.VOCAL,
        CreditRole.INSTRUMENT,
        CreditRole.PERFORMER,
        CreditRole.PROGRAMMING,
        CreditRole.ARRANGER,
        CreditRole.CONDUCTOR,
        CreditRole.REMIXER,
    }
)


class RelationType(enum.StrEnum):
    """A directed artist-to-artist relationship that reads ``subject <type> object``.

    Directions follow MusicBrainz's forward link phrases, verified against
    snapshot data: "Thundercat member_of Suicidal Tendencies", "Robert Glasper
    has_subgroup Robert Glasper & Questlove", "Malcolm McCormick performs_as Mac
    Miller", "Caitlin Evanson supported Taylor Swift", "Herbie Hancock taught
    Eric Miller".

    Personal-life relations (marriage, family) are deliberately absent: they are
    not musical connections.
    """

    MEMBER_OF = "member_of"
    HAS_SUBGROUP = "has_subgroup"
    PERFORMS_AS = "performs_as"
    COLLABORATION_IN = "collaboration_in"
    SUPPORTED = "supported"
    TAUGHT = "taught"
