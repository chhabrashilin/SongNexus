# Part 10: Development roadmap

Tier 1 (data model, ingestion, ER, graph model, algorithms, backend, graph UX, testing) is never traded for
Tier 3 features. Each phase has acceptance criteria that can be checked by a command or a demo.

```
Phase 0 ─▶ Phase 1 ─┬─▶ Phase 2 ─────────────┐
 (done)             ├─▶ Phase 3 ─▶ Phase 5 ───┼─▶ Phase 6 ─▶ Phase 7
                    └─▶ Phase 4 ─────────────┘
```

## Phase 0: Architecture and dataset validation ✅ (this draft)

Delivered: architecture, data model, algorithm and agent design; MusicBrainz snapshot (28 seeds); vertical
slice end to end; 141 backend tests + frontend tests; evaluation harnesses with recorded baselines; Docker and CI.

## Phase 1: Knowledge graph MVP (hardening + second source)

Depends on: Phase 0.
- Alembic migrations (initial migration = current models; `alembic check` in CI).
- Seed set grows to ~100 artists across more genres (and more albums per artist). Fetch time stays under 20 min.
- Second source: **Wikidata** (CC0) via the `artist_links` crosswalk, for influences and instrument/genre data, or
  Discogs data dumps (CC0) for producer and songwriter credits.
- Cross-source ER: crosswalk first, matcher second, `resolution_reviews` queue for ambiguous cases.

Acceptance: ingest of both sources is idempotent (zero inserts on re-run) with all quality checks passing; ER
precision ≥ 0.98 and recall reported on a labeled set of ≥ 200 pairs; no silent merges (every merge has a method and confidence).

## Phase 2: Exploration UX

Depends on: Phase 1 (richer data), can start in parallel.
- Track/album nodes on demand ("show the songs behind this link" as a sub-graph).
- Era filter (release years), neighbor search inside the graph, shareable URLs (state in the query string).
- Keyboard-accessible list/table view of the current graph; Playwright E2E in CI.

Acceptance: the three demo flows pass in CI E2E; usability test with 5 non-CS listeners: ≥ 4 complete "find how
A and B are connected" unaided.

## Phase 3: Algorithms and discovery

Depends on: Phase 1.
- Leiden communities (seeded) + community view; bridge artists between communities; genre-bridge discovery
  (closes the current planner limitation).
- Explainable similarity (genre Jaccard, shared collaborators, optional Node2Vec) with per-component explanations.
- "Surprising" / "genre-crossing" alternative-path rankings ([graph-algorithms.md](graph-algorithms.md)).
- Audio-feature comparison (radar/parallel coordinates) **only if** a legally usable audio source is confirmed.

Acceptance: community stability ARI ≥ 0.8 across seeds; similarity nDCG@10 beats the best single signal on a
held-out judgment set; every discovery result has an evidence panel.

## Phase 4: Search

Depends on: Phase 1.
- pg_trgm candidate generation in PostgreSQL; pgvector embeddings; reciprocal-rank fusion.

Acceptance: hybrid MRR > lexical MRR on an expanded, partly held-out set; p95 ≤ 50 ms; lexical remains the
fallback if embeddings are unavailable.

## Phase 5: Agentic AI

Depends on: Phase 3 (tools for communities/similarity/comparison).
- New tools: `compare_artists`, `find_similar`, `find_communities`, `genre_bridges`.
- Answer-level claim checking (extract (artist, work, role) triples, verify against the ledger).
- Multi-turn follow-ups ("and how about with Thundercat?").
- LLM-mode evaluation committed; effort/cost tuning against it.

Acceptance: LLM mode beats deterministic task success on the full case set; unsupported-claim rate ≤ 2%;
limitation admission 100%; cost per question reported.

## Phase 6: Evaluation and performance

Depends on: Phases 2–5.
- Load tests (k6/Locust) on Docker Compose; SLOs: API p95 < 150 ms for search/path at 50 RPS.
- Held-out search queries from anonymous usage logs; agent cases from real questions.
- OpenTelemetry exporter replacing the in-process metrics registry.

Acceptance: SLOs met and documented with recorded runs; eval sets doubled with a held-out split.

## Phase 7: Polish and deployment

Depends on: Phase 6.
- **Music Connections puzzle:** verified graph patterns (shared producer, same band, common sample source)
  → candidate groups → remove obvious/overlapping groups (set packing with overlap constraints) → difficulty estimate
  (group-member degree, cross-genre spread) → verify uniqueness of the solution → persist with evidence. The LLM
  may phrase hints *after* verification only.
- Deployment (a single VM or Cloud Run + Cloud SQL), shared cache/limiter if running more than one replica, demo script.

Acceptance: puzzles are 100% verifiable from stored evidence; a public demo passes the six-step demo script.
