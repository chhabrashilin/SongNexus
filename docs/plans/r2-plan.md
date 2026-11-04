# R2 plan: eight listener stories, built for YouTube Music

Status: **accepted 2026-11-01** (decisions at the end). Written 2026-11-01. R1 (milestones M0–M9) is
complete; its plan is preserved at tag `plan-rev3`. This plan follows the same rules: every milestone ships tested code,
docs and an eval or measurement; nothing claims YouTube Music access we do not have; every number is traceable or TBD.

## Where each story stands today

| # | Story | Today (R1) | Gap to close |
|---|---|---|---|
| S1 | **Song comparison**: structure, shared credits, sonic similarity | Song page shows credits and albums; no comparison | New: audio descriptors, shared-credit diff, explainable similarity |
| S2 | **Artist comparison**: genres, mutual collaborators, listener overlap | Compare screen: shared genres, mutual collaborators, path | Listener overlap; genre data safe for commercial use |
| S3 | **Connection web**: expand from one artist | Explore canvas + accessible list view | Polish: expansion history, "why this artist" next steps |
| S4 | **Genre selection** across exploration | Genre filter in Explore and Six degrees | Filter in Compare, Collaborations and Play; genre hierarchy; commercial-safe genres |
| S5 | **Relationship graph**: producers, labels, features | Features/producers/bands/samples edges; label mates behind a flag with no UI toggle | Label and producer views in the UI; label nodes as first-class |
| S6 | **Collaborations** breakdown | Artist page tabs (features, production, bands, credits) | Dedicated page: timeline, side projects, filters, counts by year |
| S7 | **Platform connection** (Spotify, YouTube Music, …) | One-time on-device file import (Spotify, YouTube Music Takeout, ListenBrainz, CSV) | Linked accounts with scheduled sync, encrypted tokens, disconnect = delete |
| S8 | **Friend recommendations** | None (no social features by R1 decision) | Friends, share paths/tracks/artists, inbox, block and report |

## Platform reality (affects S7, checked 2026-11-01)

- **YouTube Music** has no public listening-history API. The YouTube Data API stopped returning watch history in 2016.
  Inside YouTube Music the history is first-party, so production uses an internal adapter. Outside it, Google Takeout
  (already supported) is the only legitimate path. The reference build ships the adapter interface and a Takeout
  connector; it does not scrape or use unofficial APIs.
- **Spotify Web API**: OAuth gives recently played (last 50) and top artists. Development-mode apps are capped at a few
  allow-listed users; extended quota now requires an established business at large scale (TechCrunch, 2025). Audio
  features were restricted for new apps in Nov 2024. A Spotify connector is fine for the capstone demo; a Google
  product linking Spotify is a policy and legal question for the sponsor, not an engineering one.
- **ListenBrainz** (CC0, open API) and **Last.fm** (public API, API key) support near-real-time sync by polling.
- "Real-time" therefore means **scheduled incremental sync (every 15 min) plus "Sync now"**, stated plainly in the UI.

## Data sources

The full registry, with licenses and what each source feeds, lives in [docs/resources.md](../resources.md) (written in
R2-0). Policy (ADR 0005, R2-0): every fact carries a `source_id`; every source has a license tier.

| Tier | Meaning | Sources |
|---|---|---|
| **Production-safe** | CC0 or equivalent; usable in a commercial YouTube Music feature | MusicBrainz core, AcousticBrainz, ListenBrainz, Discogs data dumps, Wikidata |
| **Non-commercial** | Capstone only; removable by one `source_id` delete | MusicBrainz tags/genres (CC BY-NC-SA) |
| **Research-only** | Kaggle datasets and similar whose license is unclear or derived from a platform's API terms | Kaggle (per dataset, see below) |

Kaggle: most music datasets there (e.g. Spotify track and audio-feature dumps) are scraped from the Spotify API and
inherit its terms, or carry non-commercial research licenses (Last.fm 1K/360K). They are useful for **offline
evaluation** (does our similarity agree with an independent signal?) and are never served. Each one gets a row in the
registry with its stated license, the date checked, and its tier. Datasets with no stated license are not used.

## Milestones

Each milestone: pure core logic (no I/O, import-linter enforced), AIP-style API added to `openapi.json`, simple web
screen, unit + browser tests with axe scans, a flag (kill switch), docs, and a measurement against a stated budget.

### R2-0 Foundations
- Source registry: `data_sources` gains `license`, `tier`, `commercial_use`, `url`, `checked_on`; ingest refuses an
  unregistered source. `GetDataSources` API; About screen gets a **Resources** section generated from the registry.
- `docs/resources.md`: every source, what it feeds, license, attribution text, refresh cadence, how to remove it.
- ADR 0005 data-source policy. The linked-accounts and social ADRs are written in R2-6 and R2-7, where their
  decisions are made against working code.
- Done when: every row in the catalog traces to a registered source, and a test fails if one does not.
- **Done 2026-11-01.** 220 server tests (1 PostgreSQL test skipped locally), 48 web unit tests, 40 browser journeys
  with axe scans; `openapi --check` and `resources --check` in CI.

### R2-1 Commercial-safe genres and genre selection everywhere (S4, part of S2)
- Ingest Discogs genres/styles (CC0) mapped to MusicBrainz artists via existing Discogs URL relations; Wikidata
  `subclass of` for a genre hierarchy (selecting "hip hop" includes its subgenres, shown and togglable).
- Genre filter in Compare and Collaborations (Explore and Six degrees already had it); the filter state is in the URL.
  Play is not filtered: the daily puzzle is the same for everyone by design.
- Eval: genre-assignment agreement between Discogs and MusicBrainz on the overlap; coverage reported per source.
- **Done 2026-11-01.** As built: the MusicBrainz genre list (CC0) is the vocabulary; artists link to Discogs through
  MusicBrainz URL relations and Wikidata P434/P1953 (Wikidata linked far more: 2,540 artists vs 107); genre shares
  are averaged per source; `SONGNEXUS_GENRE_SOURCES` picks the served sources. Coverage 9 % → 30 % of artists;
  agreement 94 % through the hierarchy ([evaluations](../handoff/evaluations.md#genres-r2-1-measured-2026-11-01)).
  Only the masters dump is read; the 10.5 GB releases dump (credits) is not needed for genres.

### R2-2 Relationship graph (S5) and connection web polish (S3)
- Labels as first-class: label view ("artists on this label, by era"), label-mate edges togglable in the UI.
- Producer view: "produced by" hub around a producer.
- Explore: expansion breadcrumbs, undo, "expand the strongest N", edge-type legend that matches toggles.
- Budget: Explore stays ≥ 50 fps at 300 nodes on a mid-range phone profile (measured in the browser tests).
- **Done 2026-11-04.** As built: `GetLabel` and label pages (roster grouped by decade, releases, sources); labels on
  artist pages; label-mate and song evidence link to their pages; the Labels category chip already existed. The
  producer view is a direction on production collaborations (produced for / produced by / co-produced) with a
  filter. Explore: expansion trail, undo (25 steps), "Expand the 5 strongest". Frame rate: met when settled and on a
  fast CPU; a moving 300-artist web measured 22 fps median in mid-tier-phone emulation, so the phone budget stays
  **unverified** until measured on a device ([measurements](../perf/measurements.md)).

### R2-3 Collaborations breakdown (S6)
- Dedicated `/artist/:id/collaborations`: features, co-productions, side projects and bands, credits; timeline by year;
  filters (type, years, genre); each item opens its evidence. `ListCollaborations` gains year and type facets.
- Gate: on a hand-labeled set of 20 artists, recall of official collaborations present in MusicBrainz ≥ 0.95.
- **Done 2026-11-04.** As built: `/artist/:id/collaborations` with a per-year timeline (chart, keyboard, table view),
  a year range (`startYear`, `endYear`; undated links fall outside any range, and the page says so), most-first or
  chronological order, the genre filter and the producer direction; all state in the URL. The artist page keeps the
  compact panel with a link to the page. Gate, made independent of the pipeline instead of hand-labeled:
  `eval-collaborations` re-derives features, production and band links for the first 20 seed artists straight from
  the raw MusicBrainz JSON and checks the API shows them: **recall 1.000** (412 feature, 838 production, 78 band
  pairs); a unit test proves a dropped collaboration is caught. Chart colors validated with the dataviz checks;
  dark mode uses its own step (`--chart-series-1`).

### R2-4 Song comparison (S1)
- Recording descriptors from **AcousticBrainz** (CC0, by recording MBID): tempo, key and mode, time signature,
  duration, loudness, danceability and other high-level descriptors where present. Coverage is partial (frozen 2022)
  and the UI says "no audio data for this recording" rather than guessing.
- `CompareRecordings`: side-by-side structure; shared credits by role (writers, producers, engineers, performers);
  samples and covers between them; the artist path between their primary artists; a similarity score that is a
  documented weighted distance over named descriptors, each shown with its contribution (no opaque model).
- Eval: similarity vs. an independent signal (ListenBrainz co-listening, Kaggle features in research tier) on a fixed
  pair set; report rank correlation. No launch gate on a number we have not measured yet.

### R2-5 Listener overlap (S2)
- From ListenBrainz public data (CC0): for artists A and B, the share of A's listeners who also listen to B, plus
  Jaccard. Shown only when both have ≥ 50 listeners (k-anonymity threshold), always with its sample size.
- Production note in the integration guide: YouTube Music substitutes first-party aggregates with the same threshold.

### R2-6 Linked accounts and sync (S7)
- Connector interface (`fetch_since(cursor) -> listens, next_cursor`) for every provider in decision 1; YouTube
  Music via Takeout plus a first-party adapter stub with contract tests.
- Tokens encrypted at rest (envelope encryption; KMS in production, local key file in development), never logged.
- Scheduled incremental sync job with backoff and per-provider rate limits; "Sync now"; last-synced time shown.
- Disconnect deletes the token and every synced listen; export and account deletion include them.
- Synced listens feed the Library screen ("Your artists", playlist analysis) exactly like file imports.

### R2-7 Friends and sharing (S8)
- Friends by invite link or code only: no contact upload, no search by email, no public directory.
- Share an artist, a song, a comparison or a six-degrees path to a friend, with an optional note (≤ 140 chars).
- Inbox with read state; recommendations from friends appear in Library.
- Safety: friendship required to send; block (silent, mutual invisibility) and report; per-user send rate limit;
  notes pass a moderation hook (stub locally, Perspective-style classifier in production); audit log entries.
- Export and deletion cover friendships, shares and notes; deleting an account removes its shares from inboxes.

### R2-8 Hardening and handoff
- Security review and threat model update for OAuth, token storage and social surfaces; privacy assessment update.
- Load test of the new endpoints; accessibility pass; pseudo-locale pass; runbooks for sync failures and abuse reports.
- Handoff docs updated: integration guide (which adapters YouTube Music replaces), limitations, demo script.

## Decisions (2026-11-01)

1. **Linked accounts: every provider with a legitimate API or export.** Live sync: ListenBrainz, Last.fm, Libre.fm
   (Last.fm-compatible), Spotify, Deezer, Apple Music (MusicKit, needs an Apple developer token). File import (no
   history API exists): YouTube Music (Takeout), Amazon Music, Tidal and Apple Music privacy exports where their formats
   can be verified from real samples. Plus the first-party YouTube Music adapter interface. Providers needing keys ship
   behind flags and stay off until a key is configured; no unofficial or scraped APIs.
2. **Kaggle: offline evaluation only**, never served.
3. **Friends: invite link or code only.**
4. **Workflow:** branch `r2` off `v2`; one commit per milestone, then pause for review. Nothing is pushed without asking.
