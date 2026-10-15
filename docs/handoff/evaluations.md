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

## Performance (plan §23)

| Budget | Target | Result | Status |
|---|---|---|---|
| p95 SearchCatalog | ≤ 50 ms | 12.5 ms (1 client); 95 ms (8 clients, one process) | Met single-client; missed under 8-way queueing |
| p95 GetArtist, collaborations | ≤ 100 ms | 10.7 and 8.2 ms (1 client); 126 and 96 ms (8 clients) | Met single-client; GetArtist missed at 8 |
| p95 FindPath, CompareArtists | ≤ 150 ms | 27 and 15.7 ms (1 client); 101 and 118 ms (8 clients) | Met |
| p95 AnalyzePlaylist, 2,000 artists | ≤ 1.5 s | about 13 s cold | **Missed**; typical playlists of 50–150 artists take 0.3–1 s |
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
