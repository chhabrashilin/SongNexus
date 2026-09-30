import type {
  AgentResponse,
  ApiErrorBody,
  ArtistDetail,
  Category,
  CentralityResponse,
  DailyPuzzle,
  EdgeEvidenceResponse,
  EdgeProvenanceResponse,
  EntityType,
  GameCheckResponse,
  GameHint,
  GraphPayload,
  GraphStats,
  PathMode,
  PathResponse,
  SearchResponse,
  TrackDetail,
} from "../types/api";

const BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? "/api/v1";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly requestId: string | null;

  constructor(status: number, code: string, message: string, requestId: string | null) {
    super(message);
    this.status = status;
    this.code = code;
    this.requestId = requestId;
  }
}

/** Turn any failed response into an ApiError, using the backend's error envelope when present. */
export async function toApiError(response: Response): Promise<ApiError> {
  const requestId = response.headers.get("X-Request-ID");
  try {
    const body = (await response.json()) as Partial<ApiErrorBody>;
    if (body.error) {
      return new ApiError(response.status, body.error.code, body.error.message, body.error.request_id ?? requestId);
    }
  } catch {
    // Non-JSON error (e.g. a proxy page): fall through to a generic message.
  }
  return new ApiError(response.status, "http_error", `Request failed with status ${response.status}`, requestId);
}

type Query = Record<string, string | number | boolean | undefined | null>;

function url(path: string, query?: Query): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== undefined && value !== null && value !== "") params.set(key, String(value));
  }
  const qs = params.toString();
  return `${BASE}${path}${qs ? `?${qs}` : ""}`;
}

async function request<T>(path: string, init: RequestInit & { query?: Query } = {}): Promise<T> {
  const { query, ...rest } = init;
  const response = await fetch(url(path, query), {
    ...rest,
    headers: { Accept: "application/json", ...(rest.body ? { "Content-Type": "application/json" } : {}) },
  });
  if (!response.ok) throw await toApiError(response);
  return (await response.json()) as T;
}

const categoriesParam = (categories?: Category[]) => (categories?.length ? categories.join(",") : undefined);

export const api = {
  search: (q: string, signal?: AbortSignal, types?: EntityType[], limit = 8) =>
    request<SearchResponse>("/search", { query: { q, types: types?.join(","), limit }, signal }),

  artist: (id: string, signal?: AbortSignal) => request<ArtistDetail>(`/artists/${id}`, { signal }),

  track: (id: string, signal?: AbortSignal) => request<TrackDetail>(`/tracks/${id}`, { signal }),

  neighbors: (id: string, options: { categories?: Category[]; limit?: number; depth?: 1 | 2; minStrength?: number }) =>
    request<GraphPayload>(`/artists/${id}/neighbors`, {
      query: {
        categories: categoriesParam(options.categories),
        limit: options.limit,
        depth: options.depth,
        min_strength: options.minStrength,
      },
    }),

  path: (
    source: string,
    target: string,
    options: { mode?: PathMode; categories?: Category[]; maxDepth?: number; alternatives?: number },
  ) =>
    request<PathResponse>("/graph/path", {
      query: {
        source,
        target,
        mode: options.mode,
        categories: categoriesParam(options.categories),
        max_depth: options.maxDepth,
        alternatives: options.alternatives,
      },
    }),

  edge: (a: string, b: string, categories?: Category[], signal?: AbortSignal) =>
    request<EdgeEvidenceResponse>("/graph/edge", { query: { a, b, categories: categoriesParam(categories) }, signal }),

  edgeProvenance: (a: string, b: string) => request<EdgeProvenanceResponse>("/provenance/edge", { query: { a, b } }),

  centrality: (metric: "pagerank" | "betweenness" | "degree", limit = 10) =>
    request<CentralityResponse>("/graph/centrality", { query: { metric, limit, scope: "hydrated" } }),

  stats: () => request<GraphStats>("/graph/stats"),

  daily: (date?: string) => request<DailyPuzzle>("/game/daily", { query: { date } }),

  gameCheck: (fromId: string, toId: string, targetId: string) =>
    request<GameCheckResponse>("/game/check", {
      method: "POST",
      body: JSON.stringify({ from_id: fromId, to_id: toId, target_id: targetId }),
    }),

  gameHint: (fromId: string, targetId: string) =>
    request<GameHint>("/game/hint", { query: { from_id: fromId, target_id: targetId } }),

  gameSolution: (date: string) => request<PathResponse>("/game/solution", { query: { date } }),

  ask: (question: string, mode: "auto" | "deterministic" | "llm" = "auto") =>
    request<AgentResponse>("/agent/query", { method: "POST", body: JSON.stringify({ question, mode }) }),
};
