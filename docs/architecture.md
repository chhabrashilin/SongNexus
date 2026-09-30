# Part 2: System architecture

A **modular monolith**: one deployable backend with strict internal boundaries, one static frontend,
one database. Nothing is split into services until a measured need appears (see [ADR-001](decisions/ADR-001-postgres-vs-graph-database.md)).

```
                    ┌──────────────────────────────────────────────────────┐
                    │ React + TypeScript + D3 (Vite build, nginx in Docker) │
                    │ Explore · Connect · Ask · Evidence & sources          │
                    └───────────────────────┬──────────────────────────────┘
                                            │ JSON over /api/v1 (same origin)
                    ┌───────────────────────▼──────────────────────────────┐
                    │ FastAPI  (api/)  request-id · timing · error envelope │
                    │   routes ─▶ services ─▶ algorithms / repositories      │
                    ├──────────────┬───────────────┬───────────────────────┤
                    │ GraphService │ CatalogService│ AgentService          │
                    │ paths, hubs, │ details,      │ planner / Claude loop │
                    │ neighborhoods│ provenance    │ tools ─▶ services     │
                    ├──────────────┴───────┬───────┴───────────────────────┤
                    │ ReadModel (immutable, swapped atomically):            │
                    │   ArtistGraph (evidence-carrying projection)          │
                    │   SearchIndex (exact/prefix/trigram/fuzzy)            │
                    │   LRU caches keyed to this version                    │
                    └──────────────────────┬───────────────────────────────┘
                                           │ SQLAlchemy
                    ┌──────────────────────▼───────────────────────────────┐
                    │ PostgreSQL: raw_records │ canonical entities │ facts  │
                    └──────────────────────▲───────────────────────────────┘
                                           │ ingest (offline, idempotent)
                    ┌──────────────────────┴───────────────────────────────┐
                    │ Snapshot (JSONL.gz)  ◀── fetch (rate-limited, cached)  │
                    │                          ◀── MusicBrainz WS/2           │
                    └──────────────────────────────────────────────────────┘
```

## Component responsibilities

| Package | Responsibility | Must not |
|---|---|---|
| `integrations/musicbrainz` | HTTP client (rate limit, retries, cache), snapshot I/O, typed parsers | know about the canonical model |
| `pipelines` | fetch plan, canonicalization (pure), persistence, quality checks | serve requests |
| `resolution` | name → entity decisions with method and confidence | touch the database |
| `db` | ORM models, engine/session management | contain logic |
| `graph` | projection from facts; pure algorithms over adjacency maps | know about HTTP or SQL |
| `search` | lexical index and ranking | know about HTTP |
| `readmodel` | build/swap the (graph, index, caches) bundle | mutate a published model |
| `services` | use cases, limits, explanations | parse HTTP input |
| `repositories` | SQL queries | contain business rules |
| `agent` | tools, ledger, planner, LLM loop, grounding | run anything not in the allow-list |
| `api` | routing, validation, middleware, error mapping, DI container | contain business logic |
| `evaluation` | search/agent evaluation, benchmarks | be imported by the app |

Dependencies point downward only (api → services → graph/search/repositories → db). The algorithms module has
no project imports at all, which is what makes it property-testable against networkx.

## Request flows

**Degrees of separation**: `GET /api/v1/graph/path?source=&target=&mode=shortest&alternatives=2`
1. Route validates UUIDs, mode, depth (1–8) and alternatives (0–5).
2. `GraphService.path` takes the current read model and the adjacency for the requested relationship kinds (memoized per kind set).
3. Cache lookup keyed by `(source, target, mode, kinds, depth, alternatives)` in the read model's path LRU.
4. Miss: bidirectional BFS (or Dijkstra for *strongest*), then Yen for alternatives. Timings go to metrics.
5. Each hop's evidence is ranked and rendered to sentences from structured facts. An explanation is templated.
6. The response includes the algorithm used, the graph version and the latency, so results are attributable.

**Agent question**: `POST /api/v1/agent/query`
1. Per-client token bucket (the LLM path costs money).
2. Mode: Claude if configured (`auto`), else the deterministic planner; Claude failures fall back with a stated limitation.
3. Tools run through `run_tool`: Pydantic validation, then execution, then a trace entry. Results are written to the evidence ledger.
4. The grounding verifier re-checks the path against the graph and scans the answer for artist mentions no tool returned.
5. The response's `path`, `entities` and `evidence` come from the ledger; only `answer` is model text.

## Data flow

`fetch` (network) → snapshot file (the reproducibility boundary) → `ingest`:
validate → normalize → resolve → canonical rows (pure) → write with source-scoped sync → `ingestion_runs` row
→ read-model rebuild (on startup or `POST /system/reload`). Details: [data-pipeline.md](data-pipeline.md).

## Caching

| Cache | Key | Invalidation |
|---|---|---|
| Adjacency per relationship-kind set | frozenset of kinds | lives on the graph object, so it is replaced with the read model |
| Path results (LRU, 2,048) | query parameters | same: the new read model starts empty |
| Centrality / components | metric + kinds | same, and warmed in a background thread after each build |
| Text normalization | string | pure function, never stale |

There are no TTLs and no stale reads: a new ingestion produces a new graph version, and the atomic swap *is* the
invalidation. Redis is intentionally absent; a single process serves the sample comfortably. A shared cache
becomes relevant with multiple API replicas (Phase 7).

## Observability

- **Structured JSON logs** with a request ID (propagated from `X-Request-ID` or generated). It is returned in the
  response headers and in every error body.
- **Metrics** (`GET /api/v1/system/metrics`): request latency per route template (p50/p95/p99 via reservoir
  sampling), status classes, graph algorithm timings, cache hit/miss, search empty-result rate, agent tool
  latency and error counts, LLM fallbacks, unsupported-mention count. The interface mirrors OpenTelemetry
  instruments so an exporter can replace the in-process registry without touching call sites.
- **Agent traces**: every tool call's name, arguments, success, summary and latency is returned to the client
  and logged under a trace ID.
- **Ingestion runs**: status, error, per-table insert/update/delete counts, rejected records and ignored
  relation types are stored in `ingestion_runs.stats`.

## Scaling path (when, not now)

| Signal | Next step |
|---|---|
| Graph > ~5M evidence items or build > 30 s | Compact CSR arrays (NumPy) for adjacency; persist the projection |
| Multiple API replicas | Shared cache (Redis) for paths/centrality; reload broadcast |
| Queries needing multi-hop filters the projection can't express | Recursive CTEs first; a graph database only if benchmarks show a need |
| Ingestion > minutes | Incremental ingestion by raw-record content hash (already stored) |

## Repository structure (Part 8)

```
songnexus/
├── backend/
│   ├── songnexus/
│   │   ├── api/            app factory, routes, middleware, DI container, rate limiter
│   │   ├── agent/          tools, ledger, planner, Claude loop, grounding, service
│   │   ├── core/           config, text normalization, IDs, logging, metrics, errors
│   │   ├── db/             SQLAlchemy models and sessions
│   │   ├── evaluation/     search/agent evaluation, path benchmarks
│   │   ├── graph/          projection + algorithms
│   │   ├── integrations/   musicbrainz client, snapshot, parsers
│   │   ├── pipelines/      fetch, canonicalize, ingest, quality
│   │   ├── repositories/   SQL access
│   │   ├── resolution/     entity-resolution matcher
│   │   ├── schemas/        API DTOs (v1) and agent contract
│   │   ├── search/         lexical index
│   │   ├── services/       graph, catalog, explanations
│   │   ├── readmodel.py    immutable graph + index + caches
│   │   └── cli.py          `songnexus` command
│   ├── tests/              unit · integration · sample_data (regression on real snapshot)
│   ├── Dockerfile
│   └── pyproject.toml
├── frontend/               React + TS + D3 (src/components, graph, hooks, services, state, types, utils)
├── data/
│   ├── seeds/              seed artists (+ lock file with resolution decisions)
│   ├── samples/            committed MusicBrainz snapshot (CC0)
│   └── raw/                local HTTP cache (git-ignored)
├── evaluation/             labeled search & agent cases, recorded results
├── docs/                   this documentation, schema.sql, ADRs
├── scripts/                maintenance scripts (schema generation)
├── .github/workflows/ci.yml
├── docker-compose.yml · Makefile · .env.example
```

Pipelines live inside the backend package, not in a top-level `pipelines/`, because they share the canonical
model and must be importable by the CLI and tests without path hacks.
