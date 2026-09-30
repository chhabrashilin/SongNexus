# Part 6: API contract (v1)

Base path `/api/v1`. JSON only. Interactive OpenAPI docs at `/docs` when the backend runs. DTOs are defined in
`backend/songnexus/schemas/` and mirrored in `frontend/src/types/api.ts`.

Conventions: artist/track/album IDs are canonical UUIDs (stable across re-ingestion). Every response carries
`X-Request-ID` (echoed if the client sent a valid one) and `Server-Timing`. All limits are enforced server-side.

## Errors

A single envelope for every failure:

```json
{ "error": { "code": "not_found", "message": "artist … not found", "details": {}, "request_id": "2968f9427fbd40d3" } }
```

| Status | `code` | When |
|---|---|---|
| 400 | `invalid_request` | semantically invalid input (e.g. unknown relationship category) |
| 404 | `not_found` | unknown entity, or artists not directly connected (edge endpoints) |
| 422 | `validation_error` | schema violations; `details.problems[]` lists field and problem |
| 429 | `rate_limited` | agent rate limit; `details.retry_after_s` |
| 500 | `internal_error` | unexpected; logged with the request ID |

## Endpoints

| Method & path | Purpose | Key parameters |
|---|---|---|
| `GET /search` | entity search | `q` (1–120), `types` (artist,track,album), `limit` ≤ 25 |
| `GET /artists/{id}` | artist details, genres, aliases, links, dataset albums, connection summary, source URLs | |
| `GET /artists/{id}/neighbors` | graph neighborhood for visualization | `categories`, `limit` ≤ 150, `depth` 1–2, `min_strength` |
| `GET /tracks/{id}` | track credits by role, albums, source recordings | |
| `GET /graph/path` | degrees of separation | `source`, `target`, `mode` (shortest\|strongest), `categories`, `max_depth` 1–8, `alternatives` 0–5 |
| `GET /graph/edge` | all evidence for a direct connection | `a`, `b`, `categories` |
| `GET /graph/centrality` | rankings | `metric` (pagerank\|betweenness\|degree\|weighted_degree), `scope` (hydrated\|all), `limit` ≤ 100 |
| `GET /graph/stats` | graph size, components, version | |
| `GET /provenance/edge` | source facts behind a connection | `a`, `b` |
| `GET /provenance/{entity_type}/{id}` | source mappings of an entity | |
| `POST /agent/query` | grounded question answering | body `{question, mode: auto\|deterministic\|llm}` |
| `GET /game/daily` | today's SongNexus Daily puzzle (same for everyone) | `date` (optional; launch day ≤ date ≤ tomorrow UTC) |
| `POST /game/check` | is a guessed artist directly connected? evidence + steps left | body `{from_id, to_id, target_id}` |
| `GET /game/hint` | three collaborators of the current artist, at least one closer | `from_id`, `target_id` |
| `GET /game/solution` | shortest route for a day's puzzle (spoiler; client asks explicitly) | `date` |
| `GET /health` | status, graph version, row counts, LLM availability | |
| `GET /system/metrics` | counters and latency summaries | |
| `POST /system/reload` | rebuild the read model after ingestion | header `X-Admin-Token`; 404 unless configured |

`categories` is a comma-separated subset of `performance, production, contribution, sampling, membership,
engineering`. The default is everything except `engineering`.

🗺️ Planned, not implemented: `POST /compare` (Phase 3, multidimensional comparison once audio features exist),
`POST /discover` (Phase 3, similarity and communities), `GET /graph/communities` (Phase 3).

## Examples (real responses from the sample, abbreviated)

`GET /api/v1/search?q=kanye&limit=1`

```json
{ "query": "kanye",
  "results": [{ "entity_type": "artist", "id": "…", "name": "Ye", "subtitle": "hip hop, pop rap, experimental hip hop",
                "score": 0.9703, "match_type": "exact", "matched_on": "Kanye" }] }
```

`GET /api/v1/graph/path?source=<Kendrick Lamar>&target=<Taylor Swift>&alternatives=2` (second hop: strength 2.2 from 3 pieces of evidence)

```json
{ "found": true, "mode": "shortest", "algorithm": "bidirectional BFS + Yen k-shortest (k=3)",
  "categories": ["contribution", "membership", "performance", "production", "sampling"], "max_depth": 6,
  "path": { "length": 2, "cost": 2.0,
    "nodes": [{"id": "…", "name": "Kendrick Lamar", "genres": ["hip hop", "…"]}, {"name": "Greg Kurstin"}, {"name": "Taylor Swift"}],
    "hops": [{ "source": "…", "target": "…", "strength": 1.0, "evidence_total": 1,
               "evidence": [{ "kind": "produced_for", "kind_label": "production", "subject_type": "track",
                              "subject_title": "LOVE.", "sentence": "Greg Kurstin produced Kendrick Lamar's “LOVE.”",
                              "roles": {"…": "producer", "…": "primary"} }] }, "…"] },
  "alternatives": ["…"],
  "explanation": "Kendrick Lamar and Taylor Swift are 2 steps apart: Greg Kurstin produced Kendrick Lamar's “LOVE.”; then Greg Kurstin produced Taylor Swift's “I Wish You Would”.",
  "graph_version": "run-2@2026.09.1", "elapsed_ms": 7.3 }
```

`GET /api/v1/provenance/edge?a=<Kendrick Lamar>&b=<SZA>`: one fact:

```json
{ "fact_type": "track_credits", "description": "Kendrick Lamar: primary", "source": "MusicBrainz",
  "source_license": "CC0 1.0 (core data)",
  "source_urls": ["https://musicbrainz.org/recording/8b035ce9-f46a-4507-b22d-b1350cd97bfc"],
  "raw_record_url": "https://musicbrainz.org/ws/2/release/2d45efbe-…?inc=recordings%2Bartist-credits%2B…",
  "retrieved_at": "2026-09-30T02:35:39+00:00", "ingestion_run_id": 2, "pipeline_version": "2026.09.1", "confidence": 1.0 }
```

`POST /api/v1/agent/query` `{"question": "How are Kendrick Lamar and SZA connected?"}`

```json
{ "answer": "Kendrick Lamar and SZA are 1 step apart.\n1. Kendrick Lamar → SZA: Kendrick Lamar is featured on SZA's “Doves in the Wind”\nOther routes: …",
  "answer_source": "template", "mode_used": "deterministic", "intent": "connection",
  "entities": [{"id": "…", "name": "Kendrick Lamar", "entity_type": "artist"}, "…"],
  "path": { "…": "as in /graph/path" }, "evidence": ["…"],
  "tools_used": [{"step": 1, "tool": "search_entities", "arguments": {"query": "Kendrick Lamar", "entity_type": "artist"},
                  "ok": true, "summary": "'Kendrick Lamar' -> Kendrick Lamar (confidence 0.9991)", "latency_ms": 83.58}, "…"],
  "limitations": [], "grounding": {"checked": true, "verified": true, "unsupported_mentions": [], "path_verified": true},
  "trace_id": "…", "elapsed_ms": 211.4 }
```

## Versioning

Breaking changes go to `/api/v2`; additive fields may appear in v1 at any time (clients must ignore unknown
fields). Response schemas are enforced by FastAPI `response_model`, and the contract tests in
`tests/integration/test_api.py` pin the shapes the frontend relies on.
