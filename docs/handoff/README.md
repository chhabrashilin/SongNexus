# SongNexus handoff package

For engineers evaluating SongNexus as a feature of YouTube Music. SongNexus shows who made the music you love: every
connection between artists comes from a published credit, with its source one tap away. This repository is a design plus a
working reference implementation whose core logic is portable.

## Read in this order

| Document | Question it answers |
|---|---|
| [Design doc](../design/design-doc.md) | What are we building, for whom, and why these choices? |
| [Integration guide](integration-guide.md) | What would a YouTube Music team replace, keep and verify? |
| [Evaluations and final measurements](evaluations.md) | Does it work, and how do we know? |
| [Limitations](limitations.md) | What does it not do, and what is unproven? |
| [Launch review](../launch-review.md) | What stands between this and a tester launch? |
| [Demo script](../demo-script.md) | How to see it working in ten minutes |
| [API contract](../../server/openapi.json) | The AIP-style API, checked against the code in CI |
| [Decision records](../adr/) | Why sessions are server-side, why MusicBrainz data is split, how the daily puzzle is scheduled |
| [Security](../security/review-2026-10-13.md), [privacy](../privacy/pia.md), [SBOM and licenses](../sbom/README.md) | Review artifacts |
| [Runbooks](../runbooks/README.md), [SLOs](../ops/slo-and-alerting.md), [deploy guide](../deploy.md) | Operating it |

## Verify it yourself

```sh
cd server && uv sync && uv run songnexus ingest      # build the reference catalog from the committed snapshot
uv run pytest && uv run ruff check . && uv run mypy src tests && uv run lint-imports && uv run songnexus openapi --check
uv run songnexus eval-search && uv run songnexus eval-import
cd ../web && npm ci && npm run lint && npm run typecheck && npm test && npm run build
```

The browser journeys (with accessibility scans) need the API and a preview server; see [web/e2e/README.md](../../web/e2e/README.md).

## What is portable

| Piece | Where | Portability |
|---|---|---|
| Graph algorithms, search, entity resolution, playlist analysis, puzzle generation | `server/src/songnexus/core` | Pure Python with no I/O (enforced by import-linter); port the logic or call it as a library |
| API contract and semantics | `server/openapi.json`, `server/src/songnexus/service` | Contract-first; clients are generated from it |
| Evaluation sets and gates | `data/eval`, evaluators in `core/search.py` and `core/resolution.py` | Reusable on any catalog with the same labels schema |
| Explanation rules ("why connected") | `core/graph/explain.py` | Message IDs plus facts; the client renders prose in the viewer's language |
| Reference client | `web/` | Material 3 tokens, i18n catalog, accessibility-tested |
| Catalog adapter, identity, deployment | `catalog/`, `identity/`, `deploy/` | Stand-ins; see the integration guide |
