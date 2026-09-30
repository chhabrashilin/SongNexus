# Part 1: Product specification

## Problem

Music listeners experience artists as isolated names in a playlist. The real structure is a dense web of
collaboration: producers who shape a sound across dozens of artists, session players who bridge jazz
and hip-hop, bands that spin off members. That structure exists in public metadata (credits,
relationships, genres) but is scattered, inconsistently named, and presented as flat lists.

The Google brief asks for an interactive platform that turns raw public music data into intuitive
visual insight, including relationship graphs, degrees of separation, and multidimensional comparison. It is to be backed by
reliable pipelines and scalable query endpoints.

## Target users

| User | Need | What they should never need to know |
|---|---|---|
| Curious listener | "Who is behind the songs I love, and what else did they make?" | Graph theory, MusicBrainz IDs |
| Music nerd / crate digger | Surprising connections, credits, lineage across genres | SQL, APIs |
| Student / journalist | Verifiable claims with sources | How the pipeline works (but can inspect it) |
| Team / reviewers | Inspectable engineering: data quality, algorithms, evaluation | – |

## Core use cases (MVP)

1. **Find an artist or song:** typo-tolerant, alias-aware search ("kanye" finds *Ye*, "hov" finds JAY-Z).
2. **Explore a neighborhood:** a force-directed graph of the artist's collaborators, colored by relationship type,
   filterable, expandable node by node without becoming a hairball.
3. **Understand a connection:** click any link to see *why*: the tracks, albums or memberships behind it,
   and the source records behind those.
4. **Degrees of separation:** fewest steps or strongest links between two artists, with alternative routes,
   each step narrated from evidence.
5. **Ask in plain language:** "How is Miles Davis connected to Drake?" The agent calls deterministic graph tools and
   explains the result; it admits when the data cannot answer.
6. **Find the hubs:** which artists are most central, and which bridge otherwise separate parts of the network.

## Differentiators

- **Evidence-first.** Every edge is derived from stored facts with provenance; an LLM never creates a fact.
- **Explainable algorithms.** Path, ranking and matching rules are documented, tested against a reference
  implementation (networkx), and benchmarked.
- **Honest about coverage.** Missing data is reported as missing, not as a negative fact.
- **Measured, not asserted.** Search quality, agent groundedness, and algorithm performance have harnesses and
  committed results.

## MVP scope (this vertical slice)

In: MusicBrainz ingestion of a 28-artist sample; canonical model with provenance; recording deduplication;
lexical search; artist graph with six relationship categories; shortest/strongest/alternative paths; PageRank,
betweenness, degree; provenance views; grounded agent with deterministic and Claude modes; tests, evaluation,
benchmarks, Docker, CI.

Out (deliberately deferred, see [roadmap](roadmap.md)): second data source and cross-source entity resolution;
audio-feature comparison; community detection; similarity/recommendations; semantic search; Connections puzzle
generator; accounts/personalization.

## Post-MVP roadmap (summary)

| Phase | Theme | Headline outcome |
|---|---|---|
| 1 | Knowledge-graph hardening | Alembic migrations, second source (Wikidata/Discogs) with cross-source ER, larger seed set |
| 2 | Exploration UX | Track/album nodes on demand, time filters, keyboard-accessible graph list view, shareable URLs |
| 3 | Algorithms | Louvain communities, genre-bridge discovery, explainable similarity, "surprising connection" ranking |
| 4 | Search | pg_trgm + pgvector hybrid retrieval with reciprocal-rank fusion, evaluated against the current ranker |
| 5 | Agentic AI | Comparative tools, LLM-mode evaluation, multi-turn follow-ups |
| 6 | Evaluation & performance | Load tests, p95 SLOs, larger eval sets with held-out queries |
| 7 | Polish & deployment | Music Connections puzzle, deployment, demo script |

## Success measures

Product: successful-search rate (non-empty results), path queries per session, evidence-panel opens.
Engineering: search MRR, agent grounded-answer rate and unsupported-claim rate, API p95, data-quality pass rate.
Collected privacy-consciously: aggregate counters only, no user identifiers (see [security.md](security.md)).
