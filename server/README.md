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
| `fetch` | Fetches MusicBrainz data for `data/seeds` into a snapshot (the only networked step; rate-limited, cached) |
| `ingest [--snapshot PATH]` | Migrates, then ingests a snapshot. The quality gate runs inside the transaction: a failing catalog is rejected and the previous one keeps serving |
| `quality` | Runs the data-quality checks on the current catalog |
| `eval-search` | Search MRR on `data/eval/search_cases.json` (gate ≥ 0.95) |
| `eval-import` | Import name-matching precision on `data/eval/import_match_cases.json` (gate ≥ 0.98) |
| `openapi [--check]` | Writes `openapi.json`, the API contract; `--check` fails if code and contract differ |
| `purge` | Removes expired sessions and accounts deleted 28+ days ago (daily job) |
| `serve` | Local API server (deployments run uvicorn from the container) |

`scripts/build_import_eval.py` regenerates the import-matching labels from the human-verified seeds.

## Layout

| Package | Responsibility | May depend on |
|---|---|---|
| `songnexus.core` | Pure domain logic: text, model, IDs, graph, search, resolution | standard library, rapidfuzz (no I/O, no other `songnexus` package) |
| `songnexus.storage` | Database models, migrations, readers and repositories | `core` |
| `songnexus.catalog` | MusicBrainz adapter, canonicalization, ingestion, quality checks | `core`, `storage` |
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
