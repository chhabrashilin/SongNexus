# songnexus (server)

Core library, catalog pipeline and HTTP API for SongNexus. See the [design doc](../docs/design/design-doc.md)
for what and why, and the repository [README](../README.md) for a quickstart.

## Commands

```sh
uv sync                          # Python 3.12 virtualenv with every dependency (locked in uv.lock)
uv run songnexus serve --reload  # API on http://127.0.0.1:8790 (local development)
uv run songnexus <command>       # see below; results are JSON on stdout, logs on stderr
```

| Command | What it does |
|---|---|
| `migrate [REVISION] [--down]` | Applies Alembic migrations (default: head) |
| `fetch` | Fetches MusicBrainz data for `data/seeds`, plus the genre list, into a snapshot (rate-limited, cached) |
| `fetch-wikidata` | Fetches Discogs artist links and the genre hierarchy from Wikidata into a snapshot |
| `fetch-discogs --dump-date YYYYMMDD` | Downloads a Discogs masters dump (~600 MB, checksum-verified, cached in `data/raw/discogs`) and extracts catalog artists' masters into a snapshot (~14 min) |
| `fetch-acousticbrainz [--cached-only]` | Fetches audio descriptors for catalog recordings (slow service: resumable from the cache; `--cached-only` builds the snapshot offline) |
| `fetch-listenbrainz` | Fetches listener counts for all artists and co-listening rankings for artists with pages |
| `ingest [--snapshot PATH] [--no-enrichment]` | Migrates, then ingests the committed snapshots (MusicBrainz, Wikidata, Discogs). The quality gate runs inside the transaction: a failing catalog is rejected and the previous one keeps serving. `--snapshot` ingests one MusicBrainz snapshot alone |
| `quality` | Runs the data-quality checks on the current catalog |
| `eval-search` | Search MRR on `data/eval/search_cases.json` (gate ≥ 0.95) |
| `eval-import` | Import name-matching precision on `data/eval/import_match_cases.json` (gate ≥ 0.98) |
| `eval-collaborations` | Collaborations recall against the raw MusicBrainz data for 20 seed artists (gate ≥ 0.95) |
| `eval-songs [--fit-weights]` | Song similarity vs genre agreement (AUC); `--fit-weights` reruns the held-out weight fit |
| `eval-listening [--lastfm PATH]` | ListenBrainz co-listening vs Last.fm 360K listener overlap (offline research data) |
| `eval-genres` | Genre coverage per source and MusicBrainz-Discogs agreement (floors in the golden tests) |
| `resources [--check]` | Writes `docs/resources.md` from the data-source registry; `--check` fails if it is stale |
| `openapi [--check]` | Writes `openapi.json`, the API contract; `--check` fails if code and contract differ |
| `purge` | Removes expired sessions and accounts deleted 28+ days ago (daily job) |
| `serve` | Local API server (deployments run uvicorn from the container) |

`scripts/build_import_eval.py` regenerates the import-matching labels from the human-verified seeds.

Refreshing the catalog data: `fetch`, then `fetch-wikidata`, `fetch-discogs --dump-date <latest>`,
`fetch-acousticbrainz` and `fetch-listenbrainz`, then `ingest` and the evaluations; review the snapshot diffs and the unmapped Discogs names in the ingest output before
committing. Only `fetch*` commands touch the network.

Daily puzzle methods, date rules and share telemetry are described in
[Daily puzzle](../docs/daily-puzzle.md); their schemas are in `openapi.json`.

## Layout

| Package | Responsibility | May depend on |
|---|---|---|
| `songnexus.core` | Pure domain logic: text, model, IDs, graph, search, resolution | standard library, rapidfuzz (no I/O, no other `songnexus` package) |
| `songnexus.storage` | Database models, migrations, readers and repositories | `core` |
| `songnexus.catalog` | Source registry; MusicBrainz, Wikidata and Discogs adapters on a shared polite HTTP client and snapshot format; canonicalization, enrichment, ingestion, quality checks | `core`, `storage` |
| `songnexus.identity` | ID-token verification, session and CSRF tokens | `core`, `storage` |
| `songnexus.jobs` | Batch jobs (purge) | `core`, `storage` |
| `songnexus.service` | HTTP API (FastAPI), read model, middleware | everything above |

The layering is enforced by `uv run lint-imports` in CI; nothing imports `service`.

## Configuration

Every setting is an environment variable `SONGNEXUS_<NAME>` (`src/songnexus/config.py`); `.env.example`
documents the ones you need locally. Outside development the service refuses to start without
`SONGNEXUS_ALLOWED_ORIGINS` (https only) and `SONGNEXUS_FIREBASE_PROJECT_ID`, or with the Auth emulator
configured.

## Tests

`uv run pytest` runs everything hermetically on SQLite, including golden tests on the committed snapshot and
property tests against networkx and brute-force oracles. Set `SONGNEXUS_TEST_DATABASE_URL` to a disposable
PostgreSQL database to run the PostgreSQL tests too (CI does).
