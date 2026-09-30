# ADR-002: In-process lexical search now, hybrid (pg_trgm + pgvector) later

**Status:** accepted (2026-09-30)

## Context

Users type partial, misspelled, differently punctuated names ("kendrik lamar", "jay-z", "beyonce", "kanye"). The
catalog in the slice is ~3,750 searchable entities. The long-term plan includes semantic retrieval.

## Options

1. PostgreSQL full-text search: stemming is wrong for names; weak typo tolerance.
2. PostgreSQL `pg_trgm` similarity: good, but PostgreSQL-only (the tests use SQLite) and needs care to rank prefixes above fuzzy matches.
3. A separate search engine (Elasticsearch/OpenSearch): powerful, but another system, which is unjustified at this size.
4. **In-process index built with the read model** (exact + prefix + trigram candidates, explicit scoring). *(chosen)*

## Decision

Option 4, behind a narrow `SearchIndex.search(query, limit, types)` interface. It uses the same `normalize()` as
ingestion and entity resolution, so matching is consistent everywhere. Ranking is a documented formula, and it is
evaluated against an exact-match baseline (MRR 0.988 vs 0.698 on 43 labeled queries).

## Consequences

- Deterministic results, identical in tests and production, and no extra infrastructure.
- Memory and build time grow with the catalog; p95 is 33 ms in-process today.
- Phase 4 moves candidate generation to `pg_trgm` GIN indexes and adds pgvector semantic candidates, fused by
  reciprocal-rank fusion. It ships only if it beats this ranker on the same harness.
