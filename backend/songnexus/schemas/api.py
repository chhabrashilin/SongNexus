"""Public API v1 data transfer objects.

These are the contract with the frontend (mirrored in frontend/src/types/api.ts)
and are documented in docs/api.md. Internal types never leak through the API.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

EntityType = Literal["artist", "track", "album"]
PathMode = Literal["shortest", "strongest"]
CentralityMetric = Literal["pagerank", "betweenness", "degree", "weighted_degree"]


class ApiModel(BaseModel):
    model_config = {"frozen": True}


# -- search --------------------------------------------------------------------


class SearchResult(ApiModel):
    entity_type: EntityType
    id: str
    name: str
    subtitle: str
    score: float
    match_type: str
    matched_on: str


class SearchResponse(ApiModel):
    query: str
    results: list[SearchResult]


# -- catalog ---------------------------------------------------------------------


class GenreOut(ApiModel):
    name: str
    votes: int


class AliasOut(ApiModel):
    alias: str
    alias_type: str


class LinkOut(ApiModel):
    link_type: str
    url: str


class AlbumSummary(ApiModel):
    id: str
    title: str
    year: str | None


class ConnectionSummary(ApiModel):
    kind: str
    label: str
    artists: int


class ArtistDetail(ApiModel):
    id: str
    name: str
    sort_name: str | None
    artist_type: str | None
    country: str | None
    disambiguation: str | None
    begin_date: str | None
    end_date: str | None
    hydrated: bool
    genres: list[GenreOut]
    aliases: list[AliasOut]
    links: list[LinkOut]
    albums: list[AlbumSummary]
    connections: list[ConnectionSummary]
    degree: int
    source_urls: list[str]


class TrackCreditOut(ApiModel):
    artist_id: str
    artist_name: str
    role: str
    role_detail: str
    credited_as: str | None


class TrackDetail(ApiModel):
    id: str
    title: str
    length_ms: int | None
    first_release_date: str | None
    albums: list[AlbumSummary]
    credits: list[TrackCreditOut]
    source_urls: list[str]


# -- graph -------------------------------------------------------------------------


class GraphNode(ApiModel):
    id: str
    name: str
    hydrated: bool
    genres: list[str]
    degree: int
    depth: int


class GraphEdge(ApiModel):
    source: str
    target: str
    strength: float
    kinds: dict[str, int]


class GraphPayload(ApiModel):
    center: str
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    truncated: bool
    total_neighbors: int
    categories: list[str]
    graph_version: str


class EvidenceItem(ApiModel):
    kind: str
    kind_label: str
    subject_type: Literal["track", "album", "relationship"]
    subject_id: str
    subject_title: str | None
    sentence: str
    roles: dict[str, str] = Field(description="artist id -> role in this piece of evidence")


class PathHop(ApiModel):
    source: str
    target: str
    strength: float
    evidence: list[EvidenceItem]
    evidence_total: int


class PathNode(ApiModel):
    id: str
    name: str
    genres: list[str]


class PathOut(ApiModel):
    nodes: list[PathNode]
    hops: list[PathHop]
    length: int
    cost: float | None


class PathResponse(ApiModel):
    found: bool
    source: PathNode
    target: PathNode
    mode: PathMode
    algorithm: str
    categories: list[str]
    max_depth: int
    path: PathOut | None
    alternatives: list[PathOut]
    explanation: str
    graph_version: str
    elapsed_ms: float


class EdgeEvidenceResponse(ApiModel):
    a: PathNode
    b: PathNode
    strength: float
    evidence: list[EvidenceItem]
    graph_version: str


class CentralityEntry(ApiModel):
    id: str
    name: str
    score: float
    rank: int
    genres: list[str]


class CentralityResponse(ApiModel):
    metric: CentralityMetric
    algorithm: str
    exact: bool
    scope: str
    results: list[CentralityEntry]
    graph_version: str


class GraphStats(ApiModel):
    graph_version: str
    artists: int
    hydrated_artists: int
    edges: int
    evidence: int
    components: int
    largest_component: int
    built_at: str
    build_ms: float


# -- provenance ------------------------------------------------------------------


class FactProvenance(ApiModel):
    fact_type: str
    fact_id: str
    description: str
    source: str
    source_license: str
    source_urls: list[str]
    raw_record_url: str | None
    retrieved_at: str | None
    ingestion_run_id: int
    pipeline_version: str
    confidence: float


class EdgeProvenanceResponse(ApiModel):
    a: str
    b: str
    facts: list[FactProvenance]


class SourceMappingOut(ApiModel):
    source: str
    source_entity_id: str
    source_url: str | None
    match_method: str
    confidence: float
    decision: str


class EntityProvenanceResponse(ApiModel):
    entity_type: EntityType
    entity_id: str
    mappings: list[SourceMappingOut]


# -- system ------------------------------------------------------------------------


class HealthResponse(ApiModel):
    status: Literal["ok", "degraded"]
    graph_version: str
    rows: dict[str, int]
    llm_available: bool


class ErrorBody(ApiModel):
    code: str
    message: str
    details: dict[str, object] = Field(default_factory=dict)
    request_id: str | None = None


class ErrorResponse(ApiModel):
    error: ErrorBody


# -- daily game ----------------------------------------------------------------------


class DailyPuzzle(ApiModel):
    number: int
    date: str
    start: PathNode
    target: PathNode
    par: int = Field(description="length of the shortest possible chain")
    graph_version: str


class GameCheckRequest(BaseModel):
    from_id: str = Field(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
    to_id: str = Field(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
    target_id: str = Field(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


class GameCheckResponse(ApiModel):
    connected: bool
    artist: PathNode
    evidence: list[EvidenceItem]
    evidence_total: int
    distance_to_target: int | None = Field(description="steps left from the guessed artist; null if unreachable")
    reached_target: bool


class GameHint(ApiModel):
    candidates: list[PathNode] = Field(
        description="three collaborators of the current artist; at least one gets closer"
    )
