"""Data-quality checks: invariants the catalog database must satisfy.

Run after every ingestion (``songnexus quality``) and in the test suite against
the sample snapshot. Each check counts violations. A check with severity
``error`` blocks publication of the catalog (the validation gate); a ``warning``
is reported but does not block, because it can be legitimate (two real artists
can share a name).
"""

from __future__ import annotations

import enum
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from songnexus.catalog.canonicalize import SUPPLEMENTARY_SOURCE_ID
from songnexus.core.model import CreditRole, RelationType
from songnexus.storage import models as m

_DATE = re.compile(r"^\d{4}(-\d{2}(-\d{2})?)?$")
MAX_RECORDING_MS = 3 * 60 * 60 * 1000

_FACT_MODELS: tuple[type[m.Base], ...] = (
    m.ArtistAlias,
    m.ArtistLink,
    m.ArtistGenre,
    m.ReleaseArtist,
    m.ReleaseRecording,
    m.ReleaseLabel,
    m.ReleaseCredit,
    m.RecordingCredit,
    m.ArtistRelation,
)


class Severity(enum.StrEnum):
    """Whether a failing check blocks publication."""

    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True)
class QualityResult:
    """The outcome of one check."""

    name: str
    severity: Severity
    violations: int
    description: str

    @property
    def passed(self) -> bool:
        """True when the check found no violations."""
        return self.violations == 0


Check = Callable[[Session], int]


def _count(session: Session, stmt: Select[Any]) -> int:
    return int(session.scalar(stmt) or 0)


def _count_where(model: type[m.Base], *conditions: Any) -> Check:
    def check(session: Session) -> int:
        return _count(session, select(func.count()).select_from(model).where(*conditions))

    return check


def _bad_confidence(session: Session) -> int:
    total = 0
    models: tuple[type[m.Base], ...] = (*_FACT_MODELS, m.EntitySourceMapping)
    for model in models:
        confidence = model.confidence  # type: ignore[attr-defined]
        total += _count_where(model, or_(confidence < 0, confidence > 1))(session)
    return total


def _license_isolation(session: Session) -> int:
    """Genre facts come only from the supplementary source, and nothing else does."""
    misattributed = _count_where(m.ArtistGenre, m.ArtistGenre.source_id != SUPPLEMENTARY_SOURCE_ID)(
        session
    )
    for model in _FACT_MODELS:
        if model is not m.ArtistGenre:
            source = model.source_id  # type: ignore[attr-defined]
            misattributed += _count_where(model, source == SUPPLEMENTARY_SOURCE_ID)(session)
    return misattributed


def _without_mapping(entity_type: str, model: type[m.Base]) -> Check:
    mapped = select(m.EntitySourceMapping.entity_id).where(
        m.EntitySourceMapping.entity_type == entity_type
    )
    return _count_where(model, model.id.not_in(mapped))  # type: ignore[attr-defined]


def _malformed_dates(session: Session) -> int:
    columns = (
        m.Recording.first_release_date,
        m.Release.first_release_date,
        m.Artist.begin_date,
        m.Artist.end_date,
        m.ArtistRelation.begin_date,
        m.ArtistRelation.end_date,
    )
    malformed = [
        value
        for column in columns
        for value in session.scalars(select(column).where(column.is_not(None)))
        if value is not None and not _DATE.match(value)
    ]
    return len(malformed)


def _erased_names(session: Session) -> int:
    """Counts names whose normalized form is empty although the name has letters.

    A name made only of punctuation ("!!!") may legitimately normalize to empty;
    one containing letters or digits in any script must not (v0 erased
    non-Latin names this way).
    """
    pairs = (
        (m.Artist.name, m.Artist.normalized_name),
        (m.Release.title, m.Release.normalized_title),
        (m.Recording.title, m.Recording.normalized_title),
        (m.Label.name, m.Label.normalized_name),
    )
    return sum(
        1
        for name_column, normalized_column in pairs
        for name in session.scalars(select(name_column).where(normalized_column == ""))
        if any(ch.isalnum() for ch in name)
    )


def _duplicate_detailed_names(session: Session) -> int:
    stmt = (
        select(m.Artist.normalized_name)
        .where(m.Artist.detail_level != "stub")
        .group_by(m.Artist.normalized_name)
        .having(func.count() > 1)
    )
    return len(session.execute(stmt).all())


_ROLES = [r.value for r in CreditRole]
_RELATION_TYPES = [t.value for t in RelationType]
_HAS_PRIMARY = select(m.RecordingCredit.recording_id).where(
    m.RecordingCredit.role == CreditRole.PRIMARY.value
)

CHECKS: tuple[tuple[str, Severity, str, Check], ...] = (
    (
        "names_survive_normalization",
        Severity.ERROR,
        "no non-empty artist, release, recording or label name normalizes to empty",
        _erased_names,
    ),
    (
        "credit_roles_known",
        Severity.ERROR,
        "every credit role is in the closed CreditRole vocabulary",
        lambda s: (
            _count_where(m.RecordingCredit, m.RecordingCredit.role.not_in(_ROLES))(s)
            + _count_where(m.ReleaseCredit, m.ReleaseCredit.role.not_in(_ROLES))(s)
        ),
    ),
    (
        "relation_types_known",
        Severity.ERROR,
        "every artist relation type is in the closed RelationType vocabulary",
        _count_where(m.ArtistRelation, m.ArtistRelation.relation_type.not_in(_RELATION_TYPES)),
    ),
    (
        "no_self_relations",
        Severity.ERROR,
        "no artist is related to itself",
        _count_where(
            m.ArtistRelation,
            m.ArtistRelation.subject_artist_id == m.ArtistRelation.object_artist_id,
        ),
    ),
    (
        "confidence_in_range",
        Severity.ERROR,
        "every fact and mapping confidence is within [0, 1]",
        _bad_confidence,
    ),
    (
        "license_isolation",
        Severity.ERROR,
        "genre facts, and only genre facts, are attributed to the supplementary source",
        _license_isolation,
    ),
    (
        "recording_has_primary_artist",
        Severity.ERROR,
        "every recording has at least one primary artist",
        _count_where(m.Recording, m.Recording.id.not_in(_HAS_PRIMARY)),
    ),
    (
        "release_has_recordings",
        Severity.ERROR,
        "every release has at least one recording",
        _count_where(m.Release, m.Release.id.not_in(select(m.ReleaseRecording.release_id))),
    ),
    (
        "artist_has_source_mapping",
        Severity.ERROR,
        "every artist maps to a source record",
        _without_mapping("artist", m.Artist),
    ),
    (
        "release_has_source_mapping",
        Severity.ERROR,
        "every release maps to a source record",
        _without_mapping("release", m.Release),
    ),
    (
        "recording_has_source_mapping",
        Severity.ERROR,
        "every recording maps to a source record",
        _without_mapping("recording", m.Recording),
    ),
    (
        "label_has_source_mapping",
        Severity.ERROR,
        "every label maps to a source record",
        _without_mapping("label", m.Label),
    ),
    (
        "dates_well_formed",
        Severity.ERROR,
        "dates are YYYY, YYYY-MM or YYYY-MM-DD",
        _malformed_dates,
    ),
    (
        "recording_length_plausible",
        Severity.WARNING,
        "recording lengths are within (0, 3h]",
        _count_where(
            m.Recording,
            or_(m.Recording.length_ms <= 0, m.Recording.length_ms > MAX_RECORDING_MS),
        ),
    ),
    (
        "detailed_names_unique",
        Severity.WARNING,
        "no two looked-up artists share a normalized name (homonyms are legitimate but "
        "need disambiguation in the UI)",
        _duplicate_detailed_names,
    ),
)


def run_quality_checks(session: Session) -> list[QualityResult]:
    """Runs every check and returns the results in a stable order."""
    return [
        QualityResult(name, severity, check(session), description)
        for name, severity, description, check in CHECKS
    ]


def gate_passes(results: list[QualityResult]) -> bool:
    """True when no error-severity check found a violation."""
    return all(r.passed for r in results if r.severity is Severity.ERROR)
