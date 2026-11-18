# Evaluations and final measurements

Measured 2026-10-15 on the `v2` branch, a developer laptop (Windows 11, Python 3.12), the committed reference catalog
(5,854 artists). Targets come from plan §21 and §23 and were not edited after measuring. Raw history and the load-test
method are in [perf/measurements.md](../perf/measurements.md).

## Gates (all enforced in CI)

| Evaluation | Target | Result |
|---|---|---|
| Search quality: MRR on 43 labeled queries (exact, prefix, partial, typo, diacritics, aliases, recordings, releases) | ≥ 0.95 | **1.000** (precision@1 1.0, recall@5 1.0, every category 1.0) |
| Import name matching: precision on 395 labeled names | ≥ 0.98 | **0.993** (302 of 304 matched were correct); recall 0.907 |
| Homonyms auto-matched | 0 | **0 of 22** |
| Catalog quality gate | all checks pass | **15 of 15** |
| Daily puzzle fairness | 100 % | **100 %** over a 365-day window, no repeated pair within a cycle |
| Server tests | all pass | **204 passed**, 1 skipped (PostgreSQL, runs in CI) |
| Core line coverage | ≥ 90 % | **97 %** (branch coverage included) |
| Web unit tests | all pass | **48 passed** |
| Browser journeys, phone and desktop | zero serious or critical axe issues | **38 passed** |
| Contract drift (`openapi --check`) and generated types | none | none |
| Static analysis | clean | ruff, mypy, import-linter (3 contracts kept), eslint, tsc all clean |

The two import errors are labeled near misses, the cost of typo tolerance: "The Beetles" → The Beatles and
"The Weekend" → The Weeknd.

## Song similarity (R2-4, measured 2026-11-05)

`songnexus eval-songs`: the similarity score against an independent signal, genre agreement. Pairs of recordings by
different artists are labelled same-genre (shared top genre) or different-genre (no genre in common); the AUC is the
chance a same-genre pair scores above a different-genre pair (0.5 is chance). Descriptors cover 4,106 of 4,786
recordings (85.8 %).

| Measure | Result |
|---|---|
| AUC, all artists (391 same-genre, 764 different-genre pairs) | **0.598** |
| Held-out half, current weights (fitted on the other half; 2,010 / 2,656 pairs) | **0.601** |
| Held-out half, the first hand-picked weights | 0.581 |
| Per part on the development half: mood, energy, tempo, key | 0.554, 0.557, 0.528, 0.505 |

Reproduce the fit with `songnexus eval-songs --fit-weights`. Sound similarity is a modest predictor of genre, which is
expected: genre is a coarse label and the AcousticBrainz classifiers are noisy. The page calls it "how alike they
sound", never a recommendation, and shows every part.

## Listener overlap (R2-5, measured 2026-11-05)

`songnexus eval-listening`: does ListenBrainz co-listening agree with a different population? For catalog artists
present in Last.fm 360K (Celma 2010, research use; read from the archive, never stored), pairs ListenBrainz lists as
co-listened are compared with random unlisted pairs by the Jaccard overlap of their Last.fm listener sets.

| Measure | Result |
|---|---|
| Catalog artists in both | 1,096 |
| Listed pairs / random pairs | 9,247 / 9,247 |
| **AUC** | **0.889** |
| Median Jaccard, listed vs random | 0.0087 vs 0.0 |

Coverage: listener counts for 2,980 of 5,854 artists; co-listening rankings for 637 of the 698 artists with pages.

## Collaborations recall (R2-3, measured 2026-11-04)

`songnexus eval-collaborations` (gate ≥ 0.95, enforced by `tests/catalog/test_golden.py`): for the first 20 seed
artists, collaborators are re-derived from the raw MusicBrainz responses with the product's definitions, without the
pipeline's parsers or projection, and compared with `ListArtistCollaborations`.

| Type | Pairs in the raw data | Shown | Recall |
|---|---|---|---|
| Features (credited together on a recording) | 412 | 412 | **1.000** |
| Production (producer credit on a recording) | 838 | 838 | **1.000** |
| Bands ("member of band") | 78 | 78 | **1.000** |

Recall measures loss between the data and the page; it says nothing about collaborations MusicBrainz lacks.

## Genres (R2-1, measured 2026-11-01)

`songnexus eval-genres` on the committed snapshots (MusicBrainz 2026-10-07, Wikidata 2026-11-01, Discogs masters dump
2026-10-01). Agreement is measured on the 468 artists both genre sources describe.

| Measure | MusicBrainz genres (non-commercial) | Discogs (CC0) | Either |
|---|---|---|---|
| Artists with genre data, of 5,854 | 526 (9.0 %) | 1,706 (29.1 %) | **1,764 (30.1 %)** |
| Fully fetched seed artists, of 107 | 104 | 97 | |
| Profile artists, of 591 | 422 | 422 | |
| Credited-only artists (producers, session players), of 5,156 | 0 | 1,187 | |

| Agreement (MusicBrainz top genre vs Discogs genres) | Result |
|---|---|
| Exact: Discogs also carries it | **82.1 %** |
| Through the hierarchy: Discogs carries it, a subgenre or a parent | **94.2 %** |
| Mean weighted share overlap | 0.42 (Discogs tags broad genres, MusicBrainz finer ones) |

Golden-test floors, set just under these numbers: at least 1,700 artists with genre data and at least 90 % agreement
through the hierarchy (`tests/catalog/test_golden_enrichment.py`).

Linking: 2,540 catalog artists link to 3,134 Discogs artist IDs (MusicBrainz URL relations plus Wikidata P434/P1953);
59 Discogs IDs claimed by two catalog artists are dropped as ambiguous. The Discogs extract scans 2,598,586 masters in
about 14 minutes; a full ingest of all three snapshots takes about 31 s on the same laptop.

## Performance (plan §23)

| Budget | Target | Result | Status |
|---|---|---|---|
| p95 SearchCatalog | ≤ 50 ms | 12.5 ms (1 client); 95 ms (8 clients, one process) | Met single-client; missed under 8-way queueing |
| p95 GetArtist, collaborations | ≤ 100 ms | 10.7 and 8.2 ms (1 client); 126 and 96 ms (8 clients) | Met single-client; GetArtist missed at 8 |
| p95 FindPath, CompareArtists | ≤ 150 ms | 27 and 15.7 ms (1 client); 101 and 118 ms (8 clients) | Met |
| p95 AnalyzePlaylist, 2,000 artists | ≤ 1.5 s | 1.11 s cold on this laptop (was about 13 s before the 2026-10-21 optimization) | Met locally, little headroom; **unverified on a 1 vCPU instance**. 150-name playlists take about 0.1 s |
| Web initial JS | ≤ 200 KB gzip | 131.0 KB | Met |
| 100 MB import in a worker | ≤ 15 s | not measured on a real 100 MB export | Open |
| Connection web ≥ 55 fps at 300 nodes | 55 fps | not measured on a reference laptop | Open |
| LCP on mid-tier mobile, 4G | ≤ 2.5 s | not measured (Lighthouse needs a deployed build) | Open |

Server numbers come from a single local process with the load generator on the same machine, so they bound the cost
of queueing, not production behavior. They must be repeated on Cloud Run.

## Not measured

- **SUS and usability studies:** no participants have used the product; the plan's usability research (§11) has not been run.
  No usability claim is made.
- **Screen readers (NVDA, VoiceOver):** not tested; automated axe scans only.
- **Production behavior:** nothing is deployed.
