# SongNexus for YouTube Music

| | |
|---|---|
| **Status** | Draft for review |
| **Authors** | SongNexus team (UW–Madison CS 620) |
| **Reviewers** | Google project sponsors (TBD) |
| **Last updated** | 2026-10-07 |
| **Supersedes** | The v0 prototype (git tag `v0-prototype`) |

## 1. Objective

Let YouTube Music listeners see and explore the human connections behind their music: who produced, played
on, featured on and sampled the songs they love, and how any two artists connect. Every connection is backed by a
cited credit. We deliver a design that the YouTube Music team can evaluate, plus a working reference
implementation whose core logic is portable to YouTube Music's catalog.

## 2. Background

### 2.1 What the v0 prototype taught us

A prototype (tag `v0-prototype`) built a knowledge graph from MusicBrainz data for 28 seed artists
(2,259 artists in total, 13,699 credits). It had a graph explorer, path finding, a chat assistant and a daily
connection game.

Measured on v0:

| Finding | Design consequence |
|---|---|
| 10 of 28 seed names matched more than one MusicBrainz artist, and one artist had been renamed | Name resolution must refuse to guess and report ambiguity (§6.4) |
| A few mix engineers connect nearly everyone in 2 hops, so paths are true but meaningless | Relationship types are weighted, and engineering credits are excluded by default (§6.3) |
| Bidirectional search explored 16 nodes on average vs 268 for one-directional, with identical answers (300 pairs) | Bounded bidirectional BFS is the path primitive (§6.3) |

Team judgment, **not yet validated with users** (to test in M4–M5):

| Observation | Design consequence |
|---|---|
| A free-form graph explorer asks a lot of a casual listener; a daily puzzle and in-context credits ask very little | Lead with game-like and in-context surfaces (§3) |
| The assistant depended on a third-party LLM, and its grounding check cannot catch false claims about artists missing from the graph | No LLM in v1; explanations are generated deterministically from evidence (§7) |

### 2.2 Constraints of building *for* YouTube Music from outside Google

- There is **no public YouTube Music API**, and the public YouTube Data API does not expose a user's watch or
  listening history. Listeners *can* export their own history through **Google Takeout**.
- We have no access to YouTube Music's internal catalog, credits or knowledge graph. We use **MusicBrainz**
  (CC0) as a stand-in catalog behind an adapter interface. The YouTube Music team would replace that adapter.
- So the deliverable is **a design plus a portable reference implementation**, not a change to YouTube Music.

## 3. Critical user journeys (CUJs)

| CUJ | Surface in YouTube Music | The user… | Success looks like |
|---|---|---|---|
| **CUJ-1 Credits & connections** | Now Playing → a "Credits" tab next to Lyrics and Related | …taps Credits on the song that's playing and sees who made it: performers, producers, players, samples. Then they see how those people connect to artists in their library | Opens the tab; taps through to a person or an artist |
| **CUJ-2 Connect (daily game)** | A shelf on Home or Explore | …plays a once-a-day puzzle: link two artists through real collaborations, then shares a spoiler-free result | Completes; returns the next day; shares |
| **CUJ-3 Your music universe** | Library → "Your universe" | …sees how the artists they listen to connect, the hidden people who link them, and nearby artists to discover, each with a reason | Explores a connector or a suggestion; saves or plays it |
| **CUJ-4 Bring your history** | Onboarding for people switching to YouTube Music; Settings | …uploads their Spotify (or other) listening export and gets CUJ-3 immediately, without waiting to build a history | Upload succeeds; most artists match; the user reaches CUJ-3 |
| **CUJ-5 Artist connections** | Artist page → "Connected artists" | …sees an artist's strongest collaborators, grouped by relationship, each with its evidence | Taps through to a connected artist |

## 4. Goals and non-goals

**Goals**
1. Every connection shown is backed by at least one cited fact. Zero generated facts.
2. All CUJs work for listeners with no graph or music-data literacy: plain language, mobile first.
3. Core logic (graph projection, algorithms, game rules, explanations) is pure, documented and portable. It has no
   dependency on MusicBrainz, our database or our UI.
4. Listening history never leaves the user's device in raw form (§8).
5. Measured quality: every user-visible ranking or matching step has an evaluation set and a metric.

**Non-goals (v1)**
- A conversational assistant or any LLM dependency (§7.2).
- Audio playback, audio analysis or hosting media. The reference client links to YouTube Music for playback.
- Replacing YouTube Music recommendations. We add *explained* discovery next to them.
- Social features, accounts and leaderboards.
- Operating at full YouTube Music scale. We design for it (§6.3.4) and implement at sample scale.

## 5. Overview

```
            ┌──────────────── Reference web client (mobile-first, YouTube Music–styled) ─────────────────┐
            │ Now Playing: Credits │ Connect (daily) │ Your universe │ Artist: Connected │ Import history  │
            └───────────┬──────────────────────────────────────────────────────────────────┬───────────┘
                        │ HTTPS/JSON, AIP-style resources                                  │ on-device
            ┌───────────▼────────────────────────────┐                ┌────────────────────▼───────────┐
            │ Service API (stateless)                 │                │ History importers (TypeScript) │
            │ artists · recordings · connections ·    │◀─ aggregates ──│ Takeout · Spotify · CSV · …    │
            │ dailyPuzzles · universes                │   (names+counts)└────────────────────────────────┘
            └───────────┬────────────────────────────┘
            ┌───────────▼────────────────────────────┐      ◀── portable core: no I/O, no framework
            │ nexus-core: graph model · projection ·  │
            │ paths · ranking · resolution · game ·   │
            │ explanations                            │
            └───────────┬────────────────────────────┘
            ┌───────────▼────────────────────────────┐      ◀── the YouTube Music team replaces this adapter
            │ Catalog adapter: MusicBrainz snapshot   │
            │ (stand-in for YouTube Music's catalog)  │
            └────────────────────────────────────────┘
```

**Integration seam.** If YouTube Music adopted this, they would replace the catalog adapter (their catalog and
credits), the history source (their own listening history) and the client (their app). They would reuse the core
library's algorithms, rules and explanation templates, the API semantics, and the evaluation sets.

## 6. Detailed design

### 6.1 Data model

- **Entities:** Artist, Recording, Release (album). Canonical IDs are deterministic (UUIDv5 of the source key),
  so rebuilds are idempotent and URLs are stable.
- **Facts:** `Credit(artist, recording|release, role, detail)` and `ArtistRelation(subject, object, type)`.
  Roles are a closed set: primary, featured, producer, vocal, instrument, arranger, remixer, engineer, sampled.
- **Provenance on every fact:** source, source record, retrieval time, pipeline version, confidence.
- **Explicitly excluded:** personal-life relations (marriage, family). They are not musical connections, and
  surfacing them is a privacy and product risk.

### 6.2 Catalog ingestion (reference implementation)

Fetch (network, rate-limited, cached) → immutable snapshot file → offline ingest (validate → normalize →
resolve → write). Ingestion is idempotent and source-scoped: re-ingesting a snapshot changes nothing, and facts
removed upstream are removed. Data-quality invariants run after every ingest and gate the build.

### 6.3 Graph core (`nexus-core`)

1. **Projection.** An artist-to-artist graph, where each edge carries its evidence list. Edge strength is a weighted sum of
   evidence. The weights are a documented, tunable heuristic, not a claim of optimality.
2. **Default relationship set** excludes engineering credits (finding in §2.1).
3. **Algorithms**, each property-tested against a reference implementation:
   bounded bidirectional BFS (fewest steps), Dijkstra (strongest links), Yen k-shortest (alternatives),
   single-source BFS (distances for the game and universe), PageRank and betweenness (connectors).
4. **Scale path.** At catalog scale the artist graph is built offline in batch (daily), stored as sharded adjacency
   lists and served with depth-bounded searches. Every query has a hard bound on depth and expansion count, so no request is
   unbounded. The reference implementation holds the sample graph in memory behind the same interface.

### 6.4 Entity resolution

Imported history and user input contain *names*, not IDs. Resolution is a three-way decision
(**matched / ambiguous / no match**) from a documented score (edit distance and trigram similarity over names
and aliases), biased toward precision. A wrong match corrupts a user's universe, while an unmatched name only
lowers coverage. Exact source IDs, when an export provides them, short-circuit name matching. Every decision
records its method and confidence.

### 6.5 History import (CUJ-4)

Parsing happens **in the browser**. Raw files are never uploaded (§8).

| Source | File(s) | Fields used |
|---|---|---|
| YouTube Music (Google Takeout) | `watch-history.json` (JSON export option); HTML export best-effort | entries with header "YouTube Music": title, artist channel |
| Spotify: account data | `StreamingHistory_music_*.json` | `artistName`, `trackName`, `msPlayed`, `endTime` |
| Spotify: extended streaming history | `Streaming_History_Audio_*.json` | `master_metadata_album_artist_name`, `master_metadata_track_name`, `ms_played`, `ts` |
| Spotify: library | `YourLibrary.json` | saved tracks, albums and artists |
| ListenBrainz | JSON/JSONL export | artist name, track name, **artist MBIDs** (exact match) |
| Last.fm, Apple Music, other playlist tools | CSV | auto-detected artist/track/album columns; manual column mapping as a fallback |
| Anything containing the above | `.zip` (e.g. `my_spotify_data.zip`) | unpacked in the browser |

Output sent to the service: a list of `{artist name, play count, minutes, optional source IDs}` capped at the top
2,000 artists. That's enough for CUJ-3 and contains no timestamps or track-level history.

### 6.6 Features

- **Credits & connections (CUJ-1):** recording → credits grouped by role → for each credited person, their
  connection to the listener's top artists (shortest path, if within 3 steps).
- **Connect (CUJ-2):** a daily pair chosen deterministically from the date among well-known artists at distance 3–4.
  Moves are validated server-side, and each correct move reveals its evidence and the remaining distance. Hints
  always include a move that gets closer. The share card contains no spoilers.
- **Your universe (CUJ-3):** resolve the listener's artists; compute the induced subgraph; find
  **hidden connectors** (people outside the library who link several library artists); suggest **nearby artists**
  (multi-source BFS from the library), each with the path that explains it.
- **Artist connections (CUJ-5):** strongest neighbors grouped by relationship, each with evidence and source.

### 6.7 API

Resource-oriented, following Google's API Improvement Proposals (AIP-121 resources, AIP-131/132 Get/List,
AIP-136 custom methods, AIP-158 pagination, AIP-193 errors):

| Method | HTTP |
|---|---|
| GetArtist | `GET /v1/artists/{artist}` |
| ListArtistConnections | `GET /v1/artists/{artist}/connections` |
| GetRecordingCredits | `GET /v1/recordings/{recording}/credits` |
| SearchCatalog | `GET /v1/catalog:search?query=` |
| FindPath | `GET /v1/artists/{artist}:findPath?target=` |
| GetDailyPuzzle | `GET /v1/dailyPuzzles/{date}` |
| CheckPuzzleMove | `POST /v1/dailyPuzzles/{date}:checkMove` |
| CreateUniverse | `POST /v1/universes:compute` (stateless; nothing stored) |

### 6.8 Reference client

Mobile-first web client styled after YouTube Music (dark theme, Material 3 components and tokens), with one
screen per CUJ placed where it would live in the real app. It is a prototype of the surfaces, not a
YouTube Music clone, and uses no YouTube trademarks or assets.

## 7. Alternatives considered

1. **Graph database (e.g. Neo4j) as the store.** Rejected for the reference implementation. Relational storage
   with a projected graph handles provenance and constraints better and measured fast enough. At YouTube Music
   scale, the batch-built sharded adjacency in §6.3.4 is the relevant design, not a general graph DB.
2. **LLM assistant.** v0 had one. For v1 we drop it:
   - per-query cost and latency at consumer scale;
   - the residual risk of unsupported claims;
   - deterministic templates already explain paths well.

   If added later, a model may only *rephrase* an explanation built from the evidence. It never adds facts.
3. **Server-side parsing of uploaded exports.** Rejected. It would mean receiving raw, timestamped listening
   history. Browser parsing gives the same features with far less data.
4. **Embedding-based recommendations.** Out of scope. YouTube Music already recommends; our differentiation is
   *explained* discovery, where every suggestion has a path.

## 8. Privacy, security, accessibility, internationalization

- **Privacy:** raw history stays on the device. The service receives only artist-level aggregates, keeps them in
  memory for the request and logs no request bodies. Imported data can be cleared in one click. Analytics are
  aggregate counters with no identifiers. Excluded relation types are listed in §6.1.
- **Security:** strict input validation and size limits; parameterized queries; per-client rate limits; no
  secrets in the repo; dependency audits in CI; the import parser runs on untrusted files with size limits and no `eval`.
- **Accessibility:** WCAG 2.2 AA. Every graph view has an equivalent list view. Color is never the only encoding,
  and the palette is validated for color-vision deficiency.
- **Internationalization:** names are matched across scripts using source aliases (e.g. 방탄소년단 / BTS); UI
  strings are externalized; layouts are RTL-safe.

## 9. Testing plan

| Layer | What |
|---|---|
| Unit / property | algorithms vs. reference implementation; normalization; resolution decisions; game rules; import parsers per format |
| Integration | ingest → quality checks → projection; API contract tests |
| Golden data | committed MusicBrainz snapshot: known connections, search and resolution quality floors |
| End-to-end | each CUJ in a headless browser, mobile and desktop |
| Non-functional | latency budgets per endpoint (load test), accessibility audit, bundle-size budget |

Tests are hermetic: no network in CI.

## 10. Metrics

| | Metric | Target (proposed) |
|---|---|---|
| CUJ-1 | Credits tab open rate; tap-through to a person | TBD with sponsor |
| CUJ-2 | completion rate; D1/D7 return; share rate | TBD |
| CUJ-3/4 | import success rate; artist match rate (precision ≥ 0.98 on a labeled set); tap-through on connectors | precision ≥ 0.98 |
| Quality | search MRR on labeled set; path-explanation correctness (100% evidence-backed) | MRR ≥ 0.95 |
| Latency | p95 server latency, per endpoint | ≤ 150 ms (reference deployment) |

## 11. Rollout (in a YouTube Music context)

Internal dogfood → small-percentage experiment per surface behind a flag → measure §10 → expand. The capstone
version ends at a demo plus a handoff package: this doc, the core library, the API spec, evaluation sets and results.

## 12. Milestones: the step-by-step build

Each milestone is a series of small, reviewed changes. Nothing merges without tests and passing CI
([engineering standards](../engineering-standards.md)).

| # | Milestone | Done when |
|---|---|---|
| **M0** | Design review + engineering standards + clean repository | This doc is reviewed and open questions are answered (§14) |
| **M1** | Data foundation: canonical model, MusicBrainz ingestion, quality checks | Snapshot ingests idempotently; all invariants pass; CI green |
| **M2** | `nexus-core`: projection, algorithms, explanations | Property tests vs. reference; golden-path tests on the snapshot |
| **M3** | Service API v1 (AIP-style), search and resolution | Contract tests; search MRR ≥ 0.95; latency budget met |
| **M4** | Reference client shell + **CUJ-5** Artist connections + **CUJ-1** Credits | E2E on mobile and desktop; accessibility audit clean |
| **M5** | **CUJ-2** Connect daily game | Puzzle fairness tests; E2E solve flow; share card |
| **M6** | **CUJ-4** History import (Takeout, Spotify, ListenBrainz, CSV, ZIP) | Parser tests per format; match precision ≥ 0.98 on labeled set |
| **M7** | **CUJ-3** Your universe (connectors, explained suggestions) | Each insight carries a path; E2E |
| **M8** | Hardening: load test, accessibility, i18n, privacy review | Budgets met; review checklist complete |
| **M9** | Demo + handoff package | Sponsor sign-off |

## 13. Feature tracker

Every feature from the original brief and the v0 prototype, and what happens to it in v2.

| Feature | v0 | v2 plan | Notes |
|---|---|---|---|
| MusicBrainz ingestion with provenance | ✅ | M1 (port, tighten) | snapshot kept as data |
| Entity resolution (refuse to guess) | ✅ | M1/M3 | extended to import matching in M6 |
| Recording deduplication | ✅ | M1 | |
| Data-quality invariants | ✅ | M1 | gate in CI |
| Artist graph projection with evidence | ✅ | M2 | |
| Shortest / strongest / alternative paths | ✅ | M2 + M4 | surfaced inside CUJ-1/3/5 rather than a standalone tool |
| PageRank, betweenness | ✅ | M2 | powers "hidden connectors" (CUJ-3) |
| Lexical search (typos, aliases) | ✅ | M3 | |
| Provenance views | ✅ | M4 | "Source" on every evidence line |
| Force-directed graph explorer | ✅ | M7 (reduced) | a small universe view, plus an accessible list; no free-form explorer |
| Daily connection game | ✅ prototype | M5 | |
| History upload (Spotify and others) | – | M6 | requested 2026-10-06 |
| Your music universe | – | M7 | |
| Credits on Now Playing | – | M4 | |
| Chat assistant (LLM) | ✅ | **Cut** (§7.2) | may return as a rephrasing layer only |
| Agent evaluation harness | ✅ | **Cut** with the assistant | |
| Community detection, similarity | designed | After M9 | |
| Semantic / hybrid search | designed | After M9 | |
| Second catalog source (Wikidata/Discogs) | designed | After M9 | YouTube Music would supply its own catalog |
| Audio-feature comparison | – | **Cut** | no legally usable audio source; out of scope |

## 14. Open questions for the sponsor

1. **Integration reality:** is the goal a handoff package for the YouTube Music team, or will Google provide any data
   or API access (catalog credits, sandbox history)? The answer changes M1 and M6.
2. **Surfaces:** which CUJs matter most to YouTube Music? We propose CUJ-1 and CUJ-2 first.
3. **LLMs:** confirm no LLM in v1. If Google wants one later, it would be Gemini under the "rephrase only" contract.
4. **Licensing:** what license should the repository carry, and may it be public?
5. **Design system:** can we use Material 3 tokens and a YouTube Music–like dark theme in demos?
