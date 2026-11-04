# Limitations and known gaps

## Product
- **Catalog scope:** about a hundred seed artists plus everyone credited on their best-known albums (5,854 artists), from
  MusicBrainz. A missing credit means missing data, and the product says so; it is not proof two artists never worked
  together.
- **Genres** come from two sources: Discogs (CC0, from the monthly masters dump) and MusicBrainz tags
  (CC BY-NC-SA 3.0, kept apart from the CC0 core). Together they cover 30 % of catalog artists; most credited-only
  artists (producers, session players) still have none. A commercial build sets `SONGNEXUS_GENRE_SOURCES=["discogs"]`
  (ADR 0003). Discogs genres describe an artist's own masters, so a producer's genres reflect the records they
  released under their own name, not every record they worked on.
- **Discogs names outside the MusicBrainz vocabulary** (e.g. "Vocal", "Modern", "Holiday") are not used. Ingest lists
  them by frequency; `data/seeds/discogs_genre_map.json` maps the unambiguous ones after review.
- **Label rosters** list the primary artists of the releases we hold for each label (the best-known albums of seed
  artists), so they are "artists on this label in our data", never a complete roster. One catalog number is kept
  per release and label.
- **Explore frame rate** with 300 artists while the layout moves is unverified on a real phone (22 fps median in
  mid-tier emulation; 60 fps settled). See [perf/measurements.md](../perf/measurements.md).
- **The genre hierarchy** comes from Wikidata "subclass of" links and inherits their gaps and occasional cycles
  (cycles are handled; a selected genre includes everything below it).
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
