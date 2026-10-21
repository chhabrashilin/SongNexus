# Limitations and known gaps

## Product
- **Catalog scope:** about a hundred seed artists plus everyone credited on their best-known albums (5,854 artists), from
  MusicBrainz. A missing credit means missing data, and the product says so; it is not proof two artists never worked
  together.
- **Genres** come from MusicBrainz tags (CC BY-NC-SA 3.0), kept apart from the CC0 core. Producers and session players
  often have none. Commercial use needs a different genre source (ADR 0003).
- **No playback, no recommendations, no social features, no assistant.** Out of scope for R1 by decision.
- **History import** supports the formats in `web/src/importers/formats.ts`; unrecognized files are rejected with a reason.
  Name matching is conservative: ambiguous names are offered for review, never auto-matched.
- **Deferred stretch items:** shareable profile, anonymous-to-account merge, the labels toggle in the UI, server-side
  game sessions, badges and streaks beyond the local stats.
- **Long-form About and Privacy copy** is English-only (marked `lang="en"`).

## Engineering
- **AnalyzePlaylist has little headroom**: 2,000 artists take 1.11 s cold on a fast laptop against a 1.5 s budget, and
  it has not been measured on a 1 vCPU instance. The R2 design (precomputed resolutions, native candidate index) is in
  [perf/measurements.md](../perf/measurements.md).
- **Scale:** the whole graph lives in memory per instance. Fine for the sample catalog, not for a full music catalog.
- **Rate limits and caches are per instance**, not global.
- **No distributed tracing or custom metrics yet**; logs carry request ID, route, status and latency.
- **PostgreSQL** is exercised in CI only; local development and most tests use SQLite.
- **Dev-only advisories:** `npm audit` flags dependencies of `gts` (lint tooling), not shipped code.

## Unverified until a real environment exists
Everything under "Deployment" in the [launch review](../launch-review.md): the deploy workflow end to end, alert
configuration, proxy-hop handling, load budgets on Cloud Run, Lighthouse and frame-rate budgets, screen-reader behavior,
and legal review of the privacy notice, terms and the psycopg LGPL note.

## Open questions for the sponsor
See design doc §14: integration reality, priority surfaces, repository license, design-system use.
