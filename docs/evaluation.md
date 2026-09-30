# Evaluation

Principle: nothing is described as good unless a harness measured it, and every number points to a committed
result file or says **TBD**.

Recorded runs: [`evaluation/results/`](../evaluation/results/) (2026-09-30, Windows 11 laptop, Python 3.14,
SQLite, graph `run-2@2026.09.1`). Reproduce with `songnexus eval-search`, `songnexus eval-agent`, `songnexus bench`.

## Search

**Dataset:** [`evaluation/search_cases.json`](../evaluation/search_cases.json): 43 queries in 9 categories (exact,
case/diacritics, aliases/renamed, typos, prefixes, partial names, tracks, albums). Labels identify entities by
MusicBrainz ID, so they survive re-ingestion.

**Metrics:** MRR; Hit@1; Recall@5; nDCG@5 (binary relevance); p50/p95 latency. Compared against an
**exact-match baseline** (normalized name/alias equality), so the value of each matching stage is measured.

| System | MRR | Hit@1 | Recall@5 | nDCG@5 |
|---|---|---|---|---|
| Exact-match baseline | 0.698 | 0.698 | 0.698 | 0.698 |
| Lexical ranker (production) | **0.988** | 0.977 | 1.000 | 0.991 |

Per category, the baseline scores 0 on prefixes and ~0.3 on typos and partial names; the ranker is 1.0 everywhere except
partial names (0.875: "mccartney" ranks Paul McCartney second, behind his 1970 album *McCartney*, which is an
exact title match; arguably a fair result, and a candidate for an artist-over-album tie-break). Latency p50 17 ms,
p95 33 ms (in-process).

**Caveats:** team-written and not held out; small. Use it as a regression gate (CI requires MRR ≥ 0.95), not as
evidence of general quality. Phase 6 adds held-out queries sampled from real (anonymous) search logs,
especially the empty-result queries the metrics endpoint already counts.

## Agent

**Dataset:** [`evaluation/agent_cases.json`](../evaluation/agent_cases.json): 20 cases: graph reasoning (6),
direct facts (4), discovery (3), comparative (2), missing or unsupported data (5).

**Metrics:**

| Metric | Definition |
|---|---|
| Tool-selection accuracy | expected tools ⊆ successfully used tools |
| Task success | every observable expectation holds (path found/not found, max length, required entities, min evidence, limitation stated) |
| Grounded rate | grounding verifier passed (path re-verified; no unsupported mentions) |
| Unsupported-claim rate | answers mentioning a graph artist that no tool returned |
| Limitation admission | on cases that require it, at least one limitation was stated |
| Latency | p50/p95 end to end |

| Mode | Tool sel. | Task success | Grounded | Unsupported claims | Limitation admission | p50 |
|---|---|---|---|---|---|---|
| Deterministic planner | 0.90 | 0.90 | 1.00 | 0.00 | 1.00 | 47 ms |
| Claude (LLM mode) | TBD | TBD | TBD | TBD | TBD | TBD |

The deterministic planner fails both *comparative* cases by design (no comparison intent). This is the concrete
gap LLM mode should close. LLM-mode runs cost API credits; run them deliberately
(`songnexus eval-agent --mode llm`) and commit the result file.

**Known limits of the metrics:** the unsupported-mention check only detects mentions of artists that exist in
the graph. Wrong statements about present artists (for example, attributing a real credit to the wrong song) need an
LLM-mode spot check or an answer-level fact checker (Phase 5: extract claimed (artist, work, role) triples from
the answer and verify each against the ledger).

## Algorithms

Correctness: property tests against networkx (BFS/bidirectional lengths, Dijkstra costs, Yen path lengths,
PageRank to 1e-6, betweenness to 1e-9, components) on random graphs.

Performance ([path_benchmarks.json](../evaluation/results/path_benchmarks.json), 300 seeded pairs in the
1,798-artist component):

| Algorithm | Mean latency | p95 | Mean nodes expanded |
|---|---|---|---|
| BFS | 0.56 ms | 1.50 ms | 268 |
| Bidirectional BFS (production) | **0.10 ms** | 0.24 ms | **16** |
| Dijkstra (strongest mode) | 4.09 ms | 7.30 ms | 883 |

Path use case (service level, incl. evidence rendering): cold p50 0.15 ms, cached p50 0.05 ms. Length disagreements
BFS vs bidirectional: 0.

## Entity resolution

Observed on seeds: 18 of 28 resolved automatically, 10 correctly refused as ambiguous (same-name artists), 0 wrong
merges; one renamed artist found through an alias. There is no labeled pair set yet, so precision/recall is **TBD**
(Phase 1, required before any cross-source merging).

## Not yet measured

API p95 under concurrent load (Phase 6: Locust/k6 against Docker Compose); ingestion throughput at larger scale;
UI performance at 400 nodes on low-end devices.
