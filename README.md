# SongNexus

The people behind the music, and how they connect. A design and reference implementation for
**YouTube Music**: who worked with whom, how any two artists connect, and how the artists in your own
playlists link up. Every connection is backed by a credit with a source.

UW–Madison CS 620 capstone with Google.

## Status

Release 1 is being built milestone by milestone on branch `v2` (plan rev 3). The v0 prototype is preserved at
tag `v0-prototype`.

| Milestone | What | State |
|---|---|---|
| M0 | Design doc, engineering standards, decisions ([ADRs](docs/adr/)) | Done (decisions provisional, ADR 0001) |
| M1 | Catalog: MusicBrainz snapshot (107 seed artists, 5,854 artists), ingestion with provenance, quality gate | Done |
| M2 | Graph core: paths, filters, explanations, collaborations, compare, search | Done |
| M3 | API v1 (AIP-style, [contract](server/openapi.json)), deployable container | Done |
| M4 | Accounts: Google Sign-In, server sessions, preferences, blocks, Top 5, export, deletion | Done |
| M5 | Web app: Home, Artist, Explore, Six degrees, Compare, Song, You | Done |
| M6 | Playlist and history import on the device; playlist analysis | Done |
| M7 | Play: daily puzzle, non-repeating cycles, archive, local stats and share links | Implemented; review pending |
| M8–M9 | Hardening, demo and handoff | Next |

Quality gates cover server tests (including PostgreSQL in CI), web unit tests, and browser journeys on
phone and desktop with accessibility scans; search MRR 1.0 (gate 0.95); import match precision 0.993 (gate 0.98).
Performance against budgets: [docs/perf/measurements.md](docs/perf/measurements.md) (one budget is missed and
explained there).

## Run it locally (about 5 minutes)

Needs Python tooling [uv](https://docs.astral.sh/uv/) and Node 22. No database server is required.

```sh
# API: builds the catalog into a SQLite file, then serves on http://127.0.0.1:8790
cd server
uv sync
cp .env.example .env
uv run songnexus ingest          # under a minute; rejects the catalog if a quality check fails
uv run songnexus serve --reload

# Web app, in a second terminal: http://localhost:5173 (proxies /v1 to the API)
cd web
npm ci
npm run dev
```

PostgreSQL instead of SQLite: `docker compose up -d` at the repository root and use the PostgreSQL URL in
`server/.env.example`. Sign-in needs a Firebase project or the Auth emulator (see `web/.env.example`);
everything else works signed out.

### Windows / VS Code PowerShell

Open this repository folder in VS Code. In **Terminal → New Terminal**, run:

```powershell
cd server
uv sync --locked
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
uv run songnexus ingest
uv run songnexus serve --reload
```

Leave that terminal running. Open a **second terminal at the repository root**:

```powershell
cd web
npm.cmd ci
npm.cmd run dev -- --host 127.0.0.1 --strictPort
```

Open **http://127.0.0.1:5173/play** for Daily, or **http://127.0.0.1:5173/** for
Home. API readiness is at http://127.0.0.1:8790/healthz and interactive API docs
at http://127.0.0.1:8790/v1/docs. Readiness should report `catalogLoaded: true`.

`npm.cmd` works without changing PowerShell's script execution policy. The server
reads `server/.env`; the old prototype's root `.env` is not used by these commands.
The example uses SQLite at `songnexus-dev.db` in the repo root; no Docker, API key,
Firebase setup or MusicBrainz download is needed to browse or play.

After initial setup, restart with just the two serve commands. Ingest again when
the bundled snapshot changes. Stop each server with **Ctrl+C** in its terminal.
If a port is occupied, stop the existing SongNexus server before restarting;
the web proxy expects the API on 8790. Avoid switching the web port because saved
progress belongs to the browser origin.

Daily rules, API methods, storage and schedule limits: [Daily puzzle](docs/daily-puzzle.md).

## Checks

Every change must pass these (CI runs them all):

```sh
cd server && uv run ruff format --check . && uv run ruff check . && uv run mypy src tests \
  && uv run lint-imports && uv run pytest && uv run songnexus openapi --check
cd web && npm run lint && npm run typecheck && npm test && npm run build && node scripts/check-bundle-size.mjs
```

Quality gates on the reference catalog: `songnexus quality`, `songnexus eval-search`, `songnexus eval-import`.
Browser tests: [web/e2e/README.md](web/e2e/README.md).

## Repository

```
server/   Python 3.12: core library (pure), catalog pipeline, storage, identity, HTTP API     → server/README.md
web/      React + TypeScript: the reference client                                          → web/README.md
data/     samples/ the MusicBrainz snapshot · seeds/ seed artists and pinned decisions · eval/ labeled sets
deploy/   Cloud Run service and jobs (deployment runbook: docs/deploy.md)
docs/     design/ · adr/ · engineering-standards.md · qa/ reviews · perf/ measurements
```

## Read first

- [Design doc](docs/design/design-doc.md): objective, user journeys, architecture, privacy, milestones
- [Engineering standards](docs/engineering-standards.md): the bar every change meets
- [Decisions](docs/adr/): what was decided, and why
- [Deploying](docs/deploy.md): one-time GCP setup and releases (nothing is deployed until a project exists)

## Data and licensing

Catalog data comes from [MusicBrainz](https://musicbrainz.org). Its core data is CC0; genre tags are
CC BY-NC-SA and kept apart as a separate source ([ADR 0003](docs/adr/0003-musicbrainz-licensing.md)). A YouTube
Music integration would use Google's own catalog. The code is Apache-2.0, provisionally (ADR 0001, D4).
