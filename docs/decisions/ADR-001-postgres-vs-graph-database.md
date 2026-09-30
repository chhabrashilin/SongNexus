# ADR-001: PostgreSQL with a projected in-memory graph, not a graph database

**Status:** accepted (2026-09-30) · **Revisit when:** any trigger below fires

## Context

The product is graph-shaped: neighborhoods, paths, centrality. The obvious move is a graph database (Neo4j).
But the data also needs a relational model: provenance on every fact, source mappings, ingestion runs, raw records,
uniqueness constraints and idempotent upserts. The query mix is dominated by short traversals (≤ 8 hops) and
whole-graph analytics over a graph that fits comfortably in memory.

## Options

1. **Neo4j (or another graph DB) as the primary store.** Native traversals and Cypher. But it means a second
   operational system, provenance modeled as properties or reified nodes, weaker relational constraints,
   licensing/hosting questions, and team ramp-up.
2. **PostgreSQL with edges in an `edges` table and recursive CTEs for paths.** One system; but multi-hop BFS in SQL
   is slow at interactive rates, and centrality in SQL is impractical.
3. **PostgreSQL as the source of truth + an in-memory, read-only projection** rebuilt after ingestion, with
   algorithms in application code. *(chosen)*

## Decision

Option 3. Facts live in PostgreSQL with full provenance. At startup (and via admin reload) the service projects
them into an evidence-carrying artist graph and serves all traversals and analytics from memory. The projection is
versioned; caches are keyed to it.

## Consequences

- Measured on the sample: projection built in ~0.1 s (2,259 artists, 14,708 evidence items); bidirectional BFS
  p50 0.07 ms; weighted PageRank ~0.1 s; sampled betweenness ~1 s (precomputed in the background).
- One database to run, back up and test. SQLite works for tests with the same models.
- Changing edge weights or categories needs no migration, because the projection is code.
- Each API process holds a copy (memory ∝ evidence); fine at this scale, not at full-catalog scale.

## Triggers to revisit

- Projection > ~5M evidence items, build > 30 s, or memory per process > 2 GB → compact CSR arrays, persisted
  projection snapshots.
- Traversal requirements that the projection cannot express (pattern queries over heterogeneous node types at
  query time) → evaluate recursive CTEs, then a graph database, **with a benchmark on the same queries** before
  adopting it.
