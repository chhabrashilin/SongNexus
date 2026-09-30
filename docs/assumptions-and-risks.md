# Assumptions, unknowns, decisions, risks

Written before implementation and updated with what the first slice revealed.

## Assumptions

| # | Assumption | Status after the slice |
|---|---|---|
| A1 | MusicBrainz core data is CC0 and usable in an academic project with attribution | Holds; the snapshot is committed |
| A2 | Recording-level credits (producer, vocal, instrument) are dense enough for popular albums to form a connected graph | Holds: 1,798 of 2,259 artists sit in one component |
| A3 | A 28-artist sample is enough to demonstrate every algorithm and UX flow | Holds for the slice; coverage gaps are visible (e.g. McCartney ↔ Eilish has no path) |
| A4 | PostgreSQL with modeled facts is sufficient; no graph database is needed at this scale | Holds (ADR-001); path queries run in < 1 ms in memory |
| A5 | Users type names, not IDs; name ambiguity is common | Confirmed: 10 of 28 seed names had same-name artists and needed a pinned ID, and one (Kanye West → "Ye") had been renamed |

## Unknowns

- Availability and terms of the Spotify API for audio features (the brief lists Spotify "where accessible"). The
  AcousticBrainz dumps (CC0) are a candidate alternative.
- Discogs data-dump size and the effort needed to align release/credit models.
- Real query distribution. The evaluation sets are team-written until usage data exists.
- LLM-mode quality and cost per question. The harness exists; a paid run needs approval.

## Architectural decisions (see [decisions/](decisions/))

- ADR-001: PostgreSQL + in-memory projected graph, not a graph database.
- ADR-002: In-process lexical search now; pg_trgm + pgvector hybrid later, behind the same interface.
- ADR-003: One orchestrator with allow-listed deterministic tools; a deterministic planner as baseline and fallback.
- ADR-004: Entity resolution never merges silently; decisions carry method and confidence.

## Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Upstream API rate limits / outages block development | Medium | High | Snapshot-based ingestion; network only in `fetch`; resumable cache |
| Name ambiguity produces wrong merges | High | High | Matcher returns *ambiguous* instead of guessing; pinned IDs need a recorded reason |
| Mix engineers make every artist 2 hops apart (uninformative paths) | High (observed) | Medium | Engineering edges are excluded by default and can be opted in |
| LLM states relationships not in the graph | Medium | High | Ledger-sourced structured fields; grounding verifier; unsupported-mention metric |
| Prompt injection via artist names/titles in tool output | Low | Medium | Read-only allow-listed tools; sanitized, truncated tool text; system prompt marks tool output as data |
| In-memory graph outgrows RAM at full-catalog scale | Low (now) | High (later) | Documented scaling path: CSR arrays, then recursive CTEs or a graph store if benchmarks justify |
| Evaluation overfitting (small, team-written sets) | Medium | Medium | Report as regression baselines; add held-out queries from usage (Phase 6) |
| Scope creep toward "resume-driven" infrastructure | Medium | Medium | Modular monolith; every new component needs a measured need |

## Data/API dependencies

| Dependency | Used for | Required at runtime? |
|---|---|---|
| MusicBrainz WS/2 | Artists, aliases, genres, relationships, releases, recording credits | No: only `songnexus fetch` |
| Anthropic Claude API | LLM mode of the agent | No: the deterministic planner answers without it |
| PostgreSQL 16 | Production store | Yes (SQLite for tests/local dev) |

## Deliberately deferred

Second data source, audio features, community detection, similarity/recommendations, semantic search,
Connections puzzle, Alembic migrations, authentication, distributed caching. Each has a phase and acceptance
criteria in the [roadmap](roadmap.md).
