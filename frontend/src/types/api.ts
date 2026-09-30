// Mirrors backend/songnexus/schemas/api.py and schemas/agent.py (API v1).

export type EntityType = "artist" | "track" | "album";
export type PathMode = "shortest" | "strongest";
export type Category = "performance" | "production" | "contribution" | "sampling" | "engineering" | "membership";

export const ALL_CATEGORIES: Category[] = [
  "performance",
  "production",
  "contribution",
  "sampling",
  "membership",
  "engineering",
];
export const DEFAULT_CATEGORIES: Category[] = ["performance", "production", "contribution", "sampling", "membership"];

export interface SearchResult {
  entity_type: EntityType;
  id: string;
  name: string;
  subtitle: string;
  score: number;
  match_type: string;
  matched_on: string;
}

export interface SearchResponse {
  query: string;
  results: SearchResult[];
}

export interface AlbumSummary {
  id: string;
  title: string;
  year: string | null;
}

export interface ArtistDetail {
  id: string;
  name: string;
  sort_name: string | null;
  artist_type: string | null;
  country: string | null;
  disambiguation: string | null;
  begin_date: string | null;
  end_date: string | null;
  hydrated: boolean;
  genres: { name: string; votes: number }[];
  aliases: { alias: string; alias_type: string }[];
  links: { link_type: string; url: string }[];
  albums: AlbumSummary[];
  connections: { kind: string; label: string; artists: number }[];
  degree: number;
  source_urls: string[];
}

export interface TrackDetail {
  id: string;
  title: string;
  length_ms: number | null;
  first_release_date: string | null;
  albums: AlbumSummary[];
  credits: { artist_id: string; artist_name: string; role: string; role_detail: string; credited_as: string | null }[];
  source_urls: string[];
}

export interface GraphNode {
  id: string;
  name: string;
  hydrated: boolean;
  genres: string[];
  degree: number;
  depth: number;
}

export interface GraphEdge {
  source: string;
  target: string;
  strength: number;
  kinds: Record<string, number>;
}

export interface GraphPayload {
  center: string;
  nodes: GraphNode[];
  edges: GraphEdge[];
  truncated: boolean;
  total_neighbors: number;
  categories: string[];
  graph_version: string;
}

export interface EvidenceItem {
  kind: string;
  kind_label: string;
  subject_type: "track" | "album" | "relationship";
  subject_id: string;
  subject_title: string | null;
  sentence: string;
  roles: Record<string, string>;
}

export interface PathNode {
  id: string;
  name: string;
  genres: string[];
}

export interface PathHop {
  source: string;
  target: string;
  strength: number;
  evidence: EvidenceItem[];
  evidence_total: number;
}

export interface PathOut {
  nodes: PathNode[];
  hops: PathHop[];
  length: number;
  cost: number | null;
}

export interface PathResponse {
  found: boolean;
  source: PathNode;
  target: PathNode;
  mode: PathMode;
  algorithm: string;
  categories: string[];
  max_depth: number;
  path: PathOut | null;
  alternatives: PathOut[];
  explanation: string;
  graph_version: string;
  elapsed_ms: number;
}

export interface EdgeEvidenceResponse {
  a: PathNode;
  b: PathNode;
  strength: number;
  evidence: EvidenceItem[];
  graph_version: string;
}

export interface FactProvenance {
  fact_type: string;
  fact_id: string;
  description: string;
  source: string;
  source_license: string;
  source_urls: string[];
  raw_record_url: string | null;
  retrieved_at: string | null;
  ingestion_run_id: number;
  pipeline_version: string;
  confidence: number;
}

export interface EdgeProvenanceResponse {
  a: string;
  b: string;
  facts: FactProvenance[];
}

export interface CentralityResponse {
  metric: string;
  algorithm: string;
  exact: boolean;
  scope: string;
  results: { id: string; name: string; score: number; rank: number; genres: string[] }[];
  graph_version: string;
}

export interface GraphStats {
  graph_version: string;
  artists: number;
  hydrated_artists: number;
  edges: number;
  evidence: number;
  components: number;
  largest_component: number;
}

export interface ToolCallTrace {
  step: number;
  tool: string;
  arguments: Record<string, unknown>;
  ok: boolean;
  summary: string;
  latency_ms: number;
}

export interface AgentResponse {
  question: string;
  answer: string;
  answer_source: "template" | "llm";
  mode_used: "deterministic" | "llm";
  intent: string | null;
  entities: { id: string; name: string; entity_type: string }[];
  path: PathOut | null;
  evidence: EvidenceItem[];
  tools_used: ToolCallTrace[];
  limitations: string[];
  grounding: { checked: boolean; verified: boolean; unsupported_mentions: string[]; path_verified: boolean | null };
  trace_id: string;
  elapsed_ms: number;
}

export interface ApiErrorBody {
  error: { code: string; message: string; details: Record<string, unknown>; request_id: string | null };
}

export interface DailyPuzzle {
  number: number;
  date: string;
  start: PathNode;
  target: PathNode;
  par: number;
  graph_version: string;
}

export interface GameCheckResponse {
  connected: boolean;
  artist: PathNode;
  evidence: EvidenceItem[];
  evidence_total: number;
  distance_to_target: number | null;
  reached_target: boolean;
}

export interface GameHint {
  candidates: PathNode[];
}
