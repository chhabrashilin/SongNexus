"""Artist/track details and fact-level provenance."""

from __future__ import annotations

from collections import Counter
from typing import Any

from sqlalchemy import Engine

from songnexus.core.errors import NotFoundError
from songnexus.db import models as m
from songnexus.db.session import session_scope
from songnexus.graph.projection import DEFAULT_CATEGORIES, kinds_for
from songnexus.readmodel import ReadModelStore
from songnexus.repositories.catalog import CatalogRepository, source_url
from songnexus.schemas import api
from songnexus.services.explain import KIND_LABELS, evidence_sentence

MAX_ALIASES = 25


def _album_summary(album: m.Album) -> api.AlbumSummary:
    year = album.first_release_date[:4] if album.first_release_date else None
    return api.AlbumSummary(id=album.id, title=album.title, year=year)


class CatalogService:
    def __init__(self, engine: Engine, store: ReadModelStore) -> None:
        self._engine = engine
        self._store = store

    def artist(self, artist_id: str) -> api.ArtistDetail:
        graph = self._store.current.graph
        with session_scope(self._engine) as session:
            repo = CatalogRepository(session)
            artist = repo.artist(artist_id)
            if artist is None:
                raise NotFoundError(f"artist {artist_id} not found")
            kinds = kinds_for(DEFAULT_CATEGORIES)
            per_kind: Counter[str] = Counter()
            degree = 0
            for edge in graph.adj.get(artist_id, {}).values():
                present = {ev.kind for ev in edge.evidence if ev.kind in kinds}
                if present:
                    degree += 1
                per_kind.update(present)
            mappings = repo.mappings("artist", artist_id)
            return api.ArtistDetail(
                id=artist.id,
                name=artist.name,
                sort_name=artist.sort_name,
                artist_type=artist.artist_type,
                country=artist.country,
                disambiguation=artist.disambiguation,
                begin_date=artist.begin_date,
                end_date=artist.end_date,
                hydrated=artist.hydrated,
                genres=[api.GenreOut(name=name, votes=votes) for name, votes in repo.artist_genres(artist_id)],
                aliases=[api.AliasOut(alias=a.alias, alias_type=a.alias_type) for a in repo.artist_aliases(artist_id)][
                    :MAX_ALIASES
                ],
                links=[api.LinkOut(link_type=link.link_type, url=link.url) for link in repo.artist_links(artist_id)],
                albums=[_album_summary(a) for a in repo.artist_albums(artist_id)],
                connections=[
                    api.ConnectionSummary(kind=k, label=KIND_LABELS[k], artists=c) for k, c in per_kind.most_common()
                ],
                degree=degree,
                source_urls=[u for mp in mappings if (u := source_url(mp.source_id, "artist", mp.source_entity_id))],
            )

    def track(self, track_id: str) -> api.TrackDetail:
        with session_scope(self._engine) as session:
            repo = CatalogRepository(session)
            track = repo.track(track_id)
            if track is None:
                raise NotFoundError(f"track {track_id} not found")
            role_order = {"primary": 0, "featured": 1, "producer": 2}
            credits = sorted(
                (
                    api.TrackCreditOut(
                        artist_id=credit.artist_id,
                        artist_name=name,
                        role=credit.role,
                        role_detail=credit.role_detail,
                        credited_as=credit.credited_as,
                    )
                    for credit, name in repo.track_credits(track_id)
                ),
                key=lambda c: (role_order.get(c.role, 9), c.role, c.artist_name),
            )
            mappings = repo.mappings("track", track_id)
            return api.TrackDetail(
                id=track.id,
                title=track.title,
                length_ms=track.length_ms,
                first_release_date=track.first_release_date,
                albums=[_album_summary(a) for a in repo.track_albums(track_id)],
                credits=credits,
                source_urls=[u for mp in mappings if (u := source_url(mp.source_id, "track", mp.source_entity_id))],
            )

    # -- provenance -------------------------------------------------------------

    def entity_provenance(self, entity_type: str, entity_id: str) -> api.EntityProvenanceResponse:
        with session_scope(self._engine) as session:
            mappings = CatalogRepository(session).mappings(entity_type, entity_id)
            if not mappings:
                raise NotFoundError(f"no source mappings for {entity_type} {entity_id}")
            return api.EntityProvenanceResponse(
                entity_type=entity_type,
                entity_id=entity_id,
                mappings=[
                    api.SourceMappingOut(
                        source=mp.source_id,
                        source_entity_id=mp.source_entity_id,
                        source_url=source_url(mp.source_id, entity_type, mp.source_entity_id),
                        match_method=mp.match_method,
                        confidence=mp.confidence,
                        decision=mp.decision,
                    )
                    for mp in mappings
                ],
            )

    def edge_provenance(self, a: str, b: str) -> api.EdgeProvenanceResponse:
        """Trace every piece of evidence on an edge back to stored facts."""
        graph = self._store.current.graph
        edge = graph.edge(a, b)
        if edge is None:
            raise NotFoundError("these artists are not directly connected", {"a": a, "b": b})
        facts: list[api.FactProvenance] = []
        with session_scope(self._engine) as session:
            repo = CatalogRepository(session)
            seen: set[tuple[str, str]] = set()
            for ev in edge.evidence:
                if ev.subject_type == "track":
                    rows: list[Any] = list(repo.track_credit_facts(ev.subject_id, [a, b]))
                    entity_type = "track"
                elif ev.subject_type == "album":
                    rows = repo.album_credit_facts(ev.subject_id, [a, b])
                    entity_type = "album"
                else:
                    rel = repo.relationship(ev.subject_id)
                    rows = [rel] if rel is not None else []
                    entity_type = "relationship"
                for row in rows:
                    fact_id = getattr(row, "id", None) or f"{row.album_id}:{row.artist_id}"
                    key = (type(row).__name__, fact_id)
                    if key in seen:
                        continue
                    seen.add(key)
                    facts.append(
                        self._fact_provenance(
                            repo, row, fact_id, entity_type, ev.subject_id, evidence_sentence(graph, edge, ev)
                        )
                    )
        return api.EdgeProvenanceResponse(a=a, b=b, facts=facts)

    def _fact_provenance(
        self, repo: CatalogRepository, row: Any, fact_id: str, entity_type: str, subject_id: str, sentence: str
    ) -> api.FactProvenance:
        raw = repo.raw_record(row.raw_record_id)
        run = repo.run(row.ingestion_run_id)
        source = repo.source(row.source_id)
        urls: list[str] = []
        if entity_type in {"track", "album"}:
            urls = [
                u
                for mp in repo.mappings(entity_type, subject_id)
                if (u := source_url(mp.source_id, entity_type, mp.source_entity_id))
            ]
        else:
            for artist_id in (row.source_artist_id, row.target_artist_id):
                urls += [
                    u
                    for mp in repo.mappings("artist", artist_id)
                    if (u := source_url(mp.source_id, "artist", mp.source_entity_id))
                ]
        if hasattr(row, "artist_id"):
            artist = repo.artist(row.artist_id)
            name = artist.name if artist else row.artist_id
            role = getattr(row, "role", "album artist")
            detail = getattr(row, "role_detail", "")
            description = f"{name}: {role}" + (f" ({detail})" if detail else "")
        else:
            description = sentence
        return api.FactProvenance(
            fact_type=type(row).__tablename__,
            fact_id=fact_id,
            description=description,
            source=source.name if source else row.source_id,
            source_license=source.license if source else "unknown",
            source_urls=urls,
            raw_record_url=raw.url if raw else None,
            retrieved_at=raw.retrieved_at if raw else None,
            ingestion_run_id=row.ingestion_run_id,
            pipeline_version=run.pipeline_version if run else "unknown",
            confidence=row.confidence,
        )
