"""AnalyzePlaylist (US-10): how a playlist's artists connect. Stateless; nothing is stored."""

from __future__ import annotations

from collections import Counter
from typing import Annotated

from fastapi import APIRouter, Depends, Response

from songnexus.core.graph.playlist import analyze_playlist
from songnexus.core.resolution import Decision
from songnexus.service import convert
from songnexus.service import schemas as api
from songnexus.service.deps import Viewer, node_filter, rate_limited, read_model, viewer
from songnexus.service.errors import invalid_argument
from songnexus.service.ratelimit import MethodClass
from songnexus.service.readmodel import ReadModel
from songnexus.service.routes.catalog import kinds_from
from songnexus.service.routes.common import RESOURCE_ID

router = APIRouter(
    prefix="/v1", tags=["analysis"], dependencies=[Depends(rate_limited(MethodClass.ANALYZE))]
)

MAX_DISTINCT_ARTISTS = 2000  # plan §14
MAX_CANDIDATES = 3

_STATUS = {
    Decision.MATCHED: api.MatchStatus.MATCHED,
    Decision.AMBIGUOUS: api.MatchStatus.AMBIGUOUS,
    Decision.NO_MATCH: api.MatchStatus.NO_MATCH,
}


def _artist_counts(tracks: list[api.PlaylistTrack]) -> Counter[str]:
    """Counts tracks per distinct artist name, in order of first appearance."""
    counts: Counter[str] = Counter()
    for track in tracks:
        for name in dict.fromkeys(a.strip() for a in track.artists if a.strip()):
            counts[name] += 1
    return counts


@router.post(
    "/playlists:analyze", response_model=api.AnalyzePlaylistResponse, summary="AnalyzePlaylist"
)
def analyze(
    body: api.AnalyzePlaylistRequest,
    model: Annotated[ReadModel, Depends(read_model)],
    who: Annotated[Viewer, Depends(viewer)],
    response: Response,
) -> api.AnalyzePlaylistResponse:
    """Matches a playlist's artists, then measures how they connect.

    Receives track titles and artist names only (files are parsed on the
    device) and stores nothing. A name may be ``artists/{artist}`` when the user
    picked one of several candidates. Blocked artists never serve as hidden
    links or as steps on the thread.
    """
    track_counts = _artist_counts(body.tracks)
    names = list(track_counts)
    if not names:
        raise invalid_argument("No artist names in the playlist.", field="tracks")
    if len(names) > MAX_DISTINCT_ARTISTS:
        raise invalid_argument(
            f"At most {MAX_DISTINCT_ARTISTS} distinct artists per request.", field="tracks"
        )

    graph = model.graph
    explicit = {n: n.removeprefix("artists/") for n in names if RESOURCE_ID.match(n)}
    to_resolve = [n for n in names if n not in explicit]
    resolved = dict(
        zip(to_resolve, model.resolutions.resolve(model.search, to_resolve), strict=True)
    )

    rows: list[api.PlaylistArtist] = []
    matched_ids: list[str] = []
    for name in names:
        candidates: list[str] = []
        if name in explicit:
            artist_id = explicit[name]
            known = artist_id in graph.nodes
            status = api.MatchStatus.MATCHED if known else api.MatchStatus.NO_MATCH
        else:
            resolution = resolved[name]
            artist_id = resolution.entity_id or ""
            status = _STATUS[resolution.decision]
            if status is api.MatchStatus.AMBIGUOUS:
                candidates = [s.candidate.entity_id for s in resolution.ranked[:MAX_CANDIDATES]]
        matched = status is api.MatchStatus.MATCHED
        if matched:
            matched_ids.append(artist_id)
        rows.append(
            api.PlaylistArtist(
                query=name,
                track_count=track_counts[name],
                status=status,
                artist=convert.artist_summary(graph, artist_id) if matched else None,
                candidates=[
                    convert.artist_summary(graph, c) for c in candidates if c in graph.nodes
                ],
                blocked=matched and artist_id in who.blocked,
            )
        )

    kinds = kinds_from(body.categories)
    allowed = node_filter(who, [], include_unknown_genre=True, graph=graph).predicate(graph)
    result = analyze_playlist(
        graph.adjacency(kinds),
        matched_ids,
        {i: graph.nodes[i].name for i in matched_ids},
        allowed=allowed,
        not_connectors=graph.other_identities(matched_ids),
    )
    response.headers["Cache-Control"] = "private, no-store"
    return api.AnalyzePlaylistResponse(
        artists=rows,
        cohesion=api.Cohesion(
            score=None if result.cohesion is None else round(result.cohesion, 4),
            pairs_within_two=result.pairs_within_two,
            pairs=result.pairs,
        ),
        connectors=[
            api.PlaylistConnector(
                artist=convert.artist_summary(graph, c.artist_id),
                linked_to=[f"artists/{a}" for a in c.linked],
                score=round(c.score, 4),
            )
            for c in result.connectors
        ],
        links=[
            api.PlaylistLink(
                artist_a=f"artists/{a}", artist_b=f"artists/{b}", strength=round(strength, 4)
            )
            for a, b, strength in result.links
        ],
        thread=api.PlaylistThread(
            artists=[convert.artist_summary(graph, a) for a in result.thread],
            breaks=result.thread_breaks,
        ),
        graph_version=model.version,
    )
