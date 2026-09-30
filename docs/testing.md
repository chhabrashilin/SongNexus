# Testing

```bash
cd backend && ../.venv/bin/pytest                 # 141 tests + 1 PostgreSQL test (runs when configured)
cd backend && ../.venv/bin/ruff check songnexus tests && ../.venv/bin/ruff format --check songnexus tests
cd backend && ../.venv/bin/mypy songnexus         # strict
cd frontend && npm test && npm run lint && npm run typecheck && npm run build
```

PostgreSQL test: set `SONGNEXUS_TEST_DATABASE_URL=postgresql+psycopg://…` to a disposable database (CI uses a
service container).

## Layers

| Layer | Location | What it proves |
|---|---|---|
| Unit: algorithms | `tests/unit/test_algorithms.py` | BFS, bidirectional BFS, Dijkstra, Yen, PageRank, betweenness, components agree with networkx on Hypothesis-generated graphs; depth limits; bidirectional search expands fewer nodes |
| Unit: text & matching | `test_text.py`, `test_matcher.py` | normalization (idempotence, Unicode), edit distance properties, title decoration rules; matched/ambiguous/no-match decisions |
| Unit: canonicalization | `test_canonicalize.py` | featured vs primary parsing, stub vs hydrated precedence, relationship direction, recording merges, provenance on every row, rejection of invalid records, order independence |
| Unit: search, agent parts | `test_search_index.py`, `test_agent_components.py` | ranking behavior; intent parsing; grounding check (including real alias quirks); rate limiter with an injected clock; metric quantiles |
| Integration: ingestion | `tests/integration/test_ingest.py` | full pipeline into a real database; idempotency; stale-fact deletion; provenance; failed runs recorded; quality checks pass and detect violations |
| Integration: graph | `test_graph.py` | projection semantics, category filters, paths and explanations, caching across reloads, limits, errors, centrality |
| Contract: API | `test_api.py` | response shapes the frontend relies on, error envelope, request IDs, rate limiting, admin-token protection, metrics |
| Integration: LLM loop | `test_agent_llm.py` | scripted fake client: grounded answers, request configuration, invalid/unknown tool rejection, unsupported-mention flagging, refusal/API-error/truncation fallbacks, step budget |
| Integration: PostgreSQL | `test_postgres.py` | idempotent ingest, quality checks, JSONB on the production database |
| Regression: real data | `tests/sample_data/` | on the committed MusicBrainz snapshot: all quality checks, known real connections, search MRR ≥ 0.95, agent unsupported-claim rate 0 and task success ≥ 0.85 |
| Frontend unit | `frontend/src/**/*.test.ts` | graph reducer (expansion, truncation, path overlay), API error parsing |

Fixtures are **synthetic and fictional** ("Alpha Rapper", "Delta Producer") so test data can never be mistaken
for real music facts. The real data is only in the committed snapshot.

## Data-quality tests

`songnexus quality` runs 18 invariants (see [data-pipeline.md](data-pipeline.md#quality-checks-songnexus-quality)).
They run in CI on the synthetic data and the real snapshot.

## Not yet covered (roadmap)

- End-to-end browser tests in CI (Playwright). A headless-browser script was used during development to verify the three main flows,
  the mobile layout and zero console errors.
- Contract tests against the live MusicBrainz API (a `network` pytest marker is reserved; never run in CI).
- Load tests and performance budgets (Phase 6).
