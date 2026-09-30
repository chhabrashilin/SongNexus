# Part 4: Algorithm design

Conventions: V = artists, E = artist–artist edges, d = path length, b = branching factor, k = requested
alternatives. Implemented algorithms live in `backend/songnexus/graph/algorithms.py`. They are pure functions over
`Mapping[node, Mapping[neighbor, strength]]`, deterministic (ties broken by node ID), and property-tested against
networkx on random graphs (`tests/unit/test_algorithms.py`).

Status legend: ✅ implemented and tested · 🗺️ designed, planned for the phase noted.

## The graph the algorithms run on

An undirected artist graph projected from facts ([projection.py](../backend/songnexus/graph/projection.py)).
Two artists are adjacent when at least one fact connects them. Each edge keeps *all* its evidence:

| Evidence kind | Derived from | Weight |
|---|---|---|
| performed_with | both credited performers (primary/featured) on a track or album | 1.0 |
| produced_for | one produced a track/album the other performed | 1.0 |
| co_produced | both produced the same track | 0.6 |
| contributed_to | vocals/instrument/arrangement/programming on the other's track | 0.6 |
| sampled | the other's track samples this artist | 0.4 |
| engineered | mix/recording/mastering on the other's track (opt-in) | 0.25 |
| member_of | band membership, subgroup, performing name of | 3.0 |
| collaboration | member of a collaboration project | 2.0 |
| supported / taught | supporting musician / teacher | 1.0 |

`strength(edge, kinds) = Σ weight(kind)` over evidence items of the enabled kinds. The weights are a
**heuristic starting point**, not a claim of optimality: memberships outweigh a single shared track, and a
shared track outweighs a sample. They are exposed in one table so they can be evaluated (Phase 3: rank-correlation
of strengths against held-out human judgments of "how connected are these two?").

**Why project to artists instead of searching the heterogeneous artist–track graph?** Degrees of separation
must count artist steps. In a bipartite artist–track graph a band membership (1 edge) and a shared song (2 edges)
would get inconsistent hop counts. The projection keeps evidence, so nothing is lost for explanation.

**Why engineering is off by default:** in the sample, a handful of mix engineers credit hundreds of tracks,
which makes almost everyone two hops apart through someone users have never heard of. The paths are true but
uninformative. Users can opt in.

## Shortest path (degrees of separation) ✅

- **Purpose:** fewest artist-to-artist steps between A and B.
- **Input:** adjacency for the enabled kinds, source, target, `max_depth` (1–8).
- **Output:** node list (or none), nodes expanded.
- **Algorithm:** **bidirectional BFS**. It expands the smaller frontier one full level at a time, and among all meeting
  nodes found in that level it picks the one minimizing total length (then node ID). This guarantees optimality
  and determinism.
- **Complexity:** O(b^(d/2)) expanded nodes vs O(b^d) for unidirectional BFS; worst case O(V + E).
- **Measured on the sample** (300 seeded random pairs, largest component): mean nodes expanded **16 vs 268**
  for unidirectional BFS, mean latency 0.10 ms vs 0.56 ms, and zero length disagreements between the two
  ([results](../evaluation/results/path_benchmarks.json)).
- **Alternatives considered:** unidirectional BFS (kept as the oracle and benchmark baseline); A* (no admissible
  heuristic without embeddings; revisit once node embeddings exist); SQL recursive CTEs (correct but orders of
  magnitude slower per query at interactive rates; kept as the scaling fallback).

## Weighted path ("strongest links") ✅

- **Purpose:** the connection made of the strongest relationships, which is often more meaningful than the fewest hops.
- **Algorithm:** Dijkstra with edge cost `1 / strength` (positive, so Dijkstra applies; one very strong link
  beats a chain of weak ones). With `max_depth`, the search state is `(node, hops)` so the hop limit is exact.
- **Complexity:** O((V + E) log V) with a binary heap; O(D·(V + E) log(V·D)) with a depth limit D.
- **Measured:** mean 4.1 ms on the sample (it expands most of the component; there is no early bidirectional meet).
- **Alternatives:** `−log(normalized strength)` costs (a probabilistic reading; revisit with calibrated weights);
  widest-path / maximin (maximizes the weakest link; a candidate "most solid chain" mode).

## Alternative routes (Connection Explorer) ✅

- **Algorithm:** Yen's k loopless shortest paths by hop count, built on BFS with banned nodes and edges.
- **Complexity:** O(k · V · (V + E)) worst case; k ≤ 5 via the API.
- **Tested:** path lengths equal networkx `shortest_simple_paths` for the first k.
- 🗺️ **Phase 3 ranking of alternatives**, each with a documented score:
  - *most surprising* = Σ over hops of `−log P(edge kind | endpoint genres)` (rare cross-genre links score high);
  - *genre-crossing* = number of distinct top-genre transitions along the path;
  - *historically interesting* = span of first-release years across the evidence.

## Ranking ✅

| Metric | Question it answers | Algorithm | Complexity |
|---|---|---|---|
| Degree / weighted degree | Who has the most / strongest direct collaborations? | count / sum | O(V + E) |
| **PageRank** (weighted) | Who is central in the collaboration network overall? | power iteration, d = 0.85, dangling mass redistributed; ranks sum to 1 | O(iter · (V + E)) |
| **Betweenness** | Who bridges otherwise separate parts of the network? | Brandes; exact for V ≤ 800, else 500 seeded random pivots (Brandes & Pich 2007), labeled "sampled" in the API | O(V·E) exact, O(k·E) sampled |

Both are tested against networkx (PageRank within 1e-6; exact betweenness within 1e-9). Results are cached per
graph version and precomputed in the background after each build, because sampled betweenness takes ~1 s on the sample.
🗺️ Eigenvector centrality was considered and skipped: on a connected undirected graph it adds little over
PageRank for these questions.

## Community detection 🗺️ (Phase 3)

- **Purpose:** musical scenes/clusters, and bridge artists *between* communities, computed rather than guessed.
- **Algorithm:** Leiden (preferred over Louvain because it guarantees connected communities) on the weighted artist
  graph, with modularity resolution γ exposed; seeded for reproducibility.
- **Output:** `artist_communities(graph_version, algorithm, resolution, artist_id, community_id)`.
- **Evaluation:** modularity; stability across seeds (adjusted Rand index); genre coherence (entropy of top genres
  per community). Only *after* communities are computed may the LLM summarize their grounded characteristics (top
  genres, central members, representative tracks).
- **Complexity:** ~O(E) per pass in practice.

## Similarity 🗺️ (Phase 3)

`similarity(a, b) = α·audio + β·genre + γ·collaboration + δ·structural`, where:
- genre = weighted Jaccard over genre vote vectors;
- collaboration = Jaccard of neighbor sets (shared collaborators);
- structural = cosine of Node2Vec embeddings (only if they beat the simpler signals in evaluation);
- audio = cosine of standardized audio-feature means (only once an audio source exists).

The weights are fitted by maximizing nDCG@10 on a held-out set of "artists fans of X also like" judgments. The API
returns each component so every recommendation explains itself ("2 shared producers, 0.61 genre overlap").

## Entity resolution ✅ (name matching) / 🗺️ (cross-source)

- **Purpose:** map a mention (seed name, user query, record from another source) to one canonical entity, or refuse.
- **Input:** mention string; candidates `(id, name, aliases, prior)`.
- **Scoring:** `name_score = max over name+aliases of max(1 − DL(q, n)/max(|q|,|n|), trigram Jaccard(q, n))`
  on normalized strings (DL = Damerau–Levenshtein, optimal string alignment). `score = 0.9·name_score + 0.1·prior`.
- **Decision:** *matched* if score ≥ 0.90 **and** lead over the runner-up ≥ 0.08 (and two exact-name
  candidates need a double margin); *ambiguous* if ≥ 0.72; otherwise *no match*. Thresholds favor precision: a
  wrong merge corrupts the graph, while a refusal costs one human decision.
- **Complexity:** O(c · L²) for c candidates of length L.
- **Observed:** on the 28 seeds it matched 18 automatically. It refused 10 names that have same-name artists in MusicBrainz
  (Drake, Rihanna, Taylor Swift, …), and each was pinned by a human with a recorded reason. It resolved the
  renamed *Kanye West → Ye* through an alias.
- **Recording deduplication:** a deterministic blocking key (base title + primary artists); merges carry confidence 0.9.
- 🗺️ **Phase 1 cross-source:** (1) external-ID crosswalk first (MusicBrainz already provides Discogs/Wikidata
  URLs in `artist_links`); (2) otherwise candidate generation from the search index (trigram + alias blocking),
  scored with the matcher plus context features (country, active years, shared release titles); (3) *ambiguous*
  goes to `resolution_reviews`. Evaluation: precision/recall on a labeled pair set, reported at the chosen thresholds.
- Alternatives: learned pairwise classifiers (need labeled pairs first); embedding matchers (considered for
  transliterated names later).

## Search ✅ (lexical) / 🗺️ (hybrid)

- **Candidate generation:** exact key (name/alias, compact and article-free variants) + prefix range scan by bisect over sorted keys +
  trigram inverted index (top 400 keys by shared trigrams).
- **Scoring:** exact 1.0 · prefix 0.82–0.92 · every query token prefixes a key token 0.80 · fuzzy
  0.75×similarity (≥ 0.5); aliases ×0.97; final = 0.85·text + 0.15·prior (log-scaled graph degree for artists,
  credit count for tracks).
- **Measured** (43 labeled queries, [results](../evaluation/results/search_eval.json)): MRR **0.988**,
  Hit@1 0.977, Recall@5 1.0, versus 0.698 for an exact-match baseline; the gains are all in the typo, prefix and partial-name
  categories. Latency p50 17 ms / p95 33 ms in-process.
- **Complexity:** O(|candidates| · L²) per query, candidates bounded at ~800.
- 🗺️ **Phase 4 hybrid:** lexical (pg_trgm) ∪ semantic (pgvector embeddings of names, disambiguations, genres,
  album titles), fused by **reciprocal-rank fusion** `Σ 1/(60 + rank_i)`, then a graph-relevance tie-break. It ships
  only if it beats the lexical ranker's MRR on the same harness without regressing p95 latency beyond 50 ms.
