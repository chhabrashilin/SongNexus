"""ResolveLink: a link from another music app, opened in SongNexus.

``POST /v1/links:resolve`` takes a Spotify, Apple Music, YouTube Music, Deezer,
Tidal, SoundCloud, Bandcamp, Last.fm, Amazon Music or MusicBrainz link (or the
text an app shares with it) and says which artist, song or release it is here.
The web app uses it for pasted links, the search bar and the system share sheet
(the PWA share target). See ``service.link_resolver`` for the order of lookups.

Privacy: the link is not stored or logged; logs carry the service, kind and outcome.
"""

from __future__ import annotations

import threading
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response

from songnexus.core.search import EntityType, SearchDoc
from songnexus.service import convert
from songnexus.service import schemas as api
from songnexus.service.deps import app_state, rate_limited, read_model
from songnexus.service.errors import ApiError, Status
from songnexus.service.link_resolver import LinkResolver, Resolution, ResolverConfig
from songnexus.service.ratelimit import MethodClass
from songnexus.service.readmodel import ReadModel

router = APIRouter(
    prefix="/v1", tags=["links"], dependencies=[Depends(rate_limited(MethodClass.ANALYZE))]
)

_LOCK = threading.Lock()
_COLLECTIONS = {
    EntityType.ARTIST: "artists",
    EntityType.RECORDING: "recordings",
    EntityType.RELEASE: "releases",
}


def link_resolver(request: Request) -> LinkResolver:
    """The process's resolver, built on first use (tests may preset one)."""
    existing: LinkResolver | None = getattr(request.app.state, "link_resolver", None)
    if existing is not None:
        return existing
    with _LOCK:
        existing = getattr(request.app.state, "link_resolver", None)
        if existing is None:
            state = app_state(request)
            settings = state.settings
            existing = LinkResolver(
                state.outbound_http,
                ResolverConfig(
                    musicbrainz_base_url=settings.musicbrainz_base_url,
                    musicbrainz_min_interval_s=settings.musicbrainz_min_interval_s,
                    network=settings.link_lookups,
                    spotify_client_id=settings.spotify_client_id,
                    spotify_client_secret=settings.spotify_client_secret,
                ),
            )
            request.app.state.link_resolver = existing
    return existing


def _search_result(model: ReadModel, doc: SearchDoc) -> api.SearchResult:
    return api.SearchResult(
        name=f"{_COLLECTIONS[doc.entity_type]}/{doc.entity_id}",
        entity_type=api.EntityType(doc.entity_type.value.upper()),
        display_name=doc.name,
        subtitle=doc.subtitle,
        match_type="link",
        matched_on=doc.name,
        image_url=convert.image_url(model.graph, doc.entity_id),
    )


def _response(model: ReadModel, result: Resolution) -> api.ResolveLinkResponse:
    graph = model.graph
    link = result.link
    artist_ids = [a for a in result.artist_ids if a in graph.nodes]
    recording = None
    if result.recording_id and (doc := model.search.get(result.recording_id)):
        recording = api.RecordingSummary(
            name=f"recordings/{doc.entity_id}",
            display_name=doc.name,
            artists=[convert.artist_summary(graph, a) for a in doc.artist_ids if a in graph.nodes],
        )
        artist_ids = artist_ids or [a for a in doc.artist_ids if a in graph.nodes]
    release = None
    if result.release_id and (doc := model.search.get(result.release_id)):
        release = _search_result(model, doc)
    candidates = [
        _search_result(model, doc)
        for _, entity_id in result.candidates
        if (doc := model.search.get(entity_id)) is not None
    ]
    return api.ResolveLinkResponse(
        outcome=api.LinkOutcome(result.outcome.value),
        service=api.LinkService(link.service.value) if link else None,
        kind=api.LinkKind(link.kind.value) if link else None,
        artist=convert.artist_summary(graph, artist_ids[0]) if artist_ids else None,
        recording=recording,
        release=release,
        candidates=candidates,
        title=result.title or None,
        artist_names=result.artist_names[:10],
        tracks=[
            api.PlaylistTrack(title=title[:300], artists=[a[:300] for a in artists][:10])
            for title, artists in result.tracks
            if artists
        ],
        via=list(dict.fromkeys(result.via)),
        graph_version=model.version,
    )


@router.post("/links:resolve", response_model=api.ResolveLinkResponse, summary="ResolveLink")
def resolve_link(
    body: api.ResolveLinkRequest,
    request: Request,
    model: Annotated[ReadModel, Depends(read_model)],
    resolver: Annotated[LinkResolver, Depends(link_resolver)],
    response: Response,
) -> api.ResolveLinkResponse:
    """Says which artist, song or release a link from another app is in SongNexus."""
    if not app_state(request).flags.get("linkResolver", True):
        raise ApiError(Status.UNAVAILABLE, "Opening links is switched off.", reason="FLAG_OFF")
    result = resolver.resolve(model, body.url)
    # Same link, same catalog version: the same answer. Never shared between users'
    # caches, because a link can carry who shared it.
    response.headers["Cache-Control"] = "private, max-age=3600"
    return _response(model, result)
