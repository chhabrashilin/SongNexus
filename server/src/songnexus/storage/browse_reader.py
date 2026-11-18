"""Reads the facts behind browse surfaces (shelves, genre pages, recommendations).

One pass over recordings, credits, track lists, labels and aggregate listening,
materialized so the session can close. The service calls it once per catalog
version and keeps the result with the read model.
"""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from songnexus.core.browse import BrowseFacts, LabelFact, RecordingFact
from songnexus.storage import models as m


def read_browse_facts(session: Session) -> BrowseFacts:
    """Loads the browse facts for the current catalog."""
    credits: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for recording_id, artist_id, role in session.execute(
        select(m.RecordingCredit.recording_id, m.RecordingCredit.artist_id, m.RecordingCredit.role)
    ):
        credits[recording_id].add((artist_id, role))
    recordings = [
        RecordingFact(recording_id, title, date, tuple(sorted(credits.get(recording_id, ()))))
        for recording_id, title, date in session.execute(
            select(m.Recording.id, m.Recording.title, m.Recording.first_release_date).order_by(
                m.Recording.id
            )
        )
    ]

    tracks: dict[str, list[tuple[int, int, str]]] = defaultdict(list)
    for release_id, disc, position, recording_id in session.execute(
        select(
            m.ReleaseRecording.release_id,
            m.ReleaseRecording.disc_number,
            m.ReleaseRecording.position,
            m.ReleaseRecording.recording_id,
        )
    ):
        tracks[release_id].append((disc, position, recording_id))

    release_artists: dict[str, list[str]] = defaultdict(list)
    for release_id, artist_id in session.execute(
        select(m.ReleaseArtist.release_id, m.ReleaseArtist.artist_id).order_by(
            m.ReleaseArtist.release_id, m.ReleaseArtist.position
        )
    ):
        release_artists[release_id].append(artist_id)

    label_releases: dict[str, set[str]] = defaultdict(set)
    for release_id, label_id in session.execute(
        select(m.ReleaseLabel.release_id, m.ReleaseLabel.label_id)
    ):
        label_releases[label_id].add(release_id)
    labels = [
        LabelFact(
            label_id,
            name,
            frozenset(label_releases[label_id]),
            frozenset(a for r in label_releases[label_id] for a in release_artists.get(r, ())),
        )
        for label_id, name in session.execute(select(m.Label.id, m.Label.name).order_by(m.Label.id))
        if label_id in label_releases
    ]

    colistening: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for artist_id, other, rank in session.execute(
        select(
            m.ArtistCoListening.artist_id,
            m.ArtistCoListening.other_artist_id,
            m.ArtistCoListening.rank,
        )
    ):
        colistening[artist_id].append((other, rank))
    # Not dict(result): a SQLAlchemy result has keys(), so dict() would read it as a mapping.
    listeners: dict[str, int] = {}
    for artist_id, count in session.execute(
        select(m.ArtistAudience.artist_id, m.ArtistAudience.listeners)
    ):
        listeners[artist_id] = count
    return BrowseFacts(
        recordings=recordings,
        release_tracks={r: tuple(t for _, _, t in sorted(rows)) for r, rows in tracks.items()},
        release_artists={r: tuple(a) for r, a in release_artists.items()},
        labels=labels,
        colistening={a: sorted(rows, key=lambda x: x[1]) for a, rows in colistening.items()},
        listeners=listeners,
    )
