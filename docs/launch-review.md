# Launch review (M8-06)

Prepared 2026-10-13 from what has been built and measured. "Open" items need things this repository cannot supply: a GCP
project, assistive-technology testers, or a legal contact. Nothing is deployed yet.

| Area | Evidence | Status |
|---|---|---|
| Functionality | M0–M7 complete: search, artist pages, connection web, six degrees, compare, daily puzzle with archive, playlist import and analysis, accounts. 204 server tests, 46+ web tests, 38 browser journeys on phone and desktop | Ready |
| Accessibility (automated) | axe at WCAG 2.2 AA on every journey, zero serious or critical; the same scan in both pseudo-locales (`pseudo.spec.ts`) | Ready |
| Accessibility (manual) | NVDA, VoiceOver and a keyboard-only pass are **not done** | **Open** |
| Internationalization | message catalog, ICU plurals, logical CSS properties, pseudo-localization (long text and RTL) with no overflow; long-form About and Privacy copy is English-only by decision | Ready for en-US |
| Performance | [measurements](perf/measurements.md): all read budgets met at one client; 8 concurrent clients on one process miss search and GetArtist p95; AnalyzePlaylist at 2,000 artists misses its budget (documented, R2 path) | Partly met; re-measure on Cloud Run |
| Security | [review](security/review-2026-10-13.md): no critical or high findings; CSP and importer fuzzing now tested | Ready for testers; S4 and S6 open |
| Privacy | [PIA](privacy/pia.md): on-device import, no third-party analytics, export and delete tested | Notice and terms need legal review |
| Observability | [SLOs and alerts](ops/slo-and-alerting.md) and [runbooks](runbooks/README.md) written; JSON logs with request ID | Alerts not yet configured (no project) |
| Supply chain | [SBOMs and license audit](sbom/README.md); audits clean for shipped dependencies | Ready |
| Data quality | quality gate inside the ingest transaction; search MRR and import precision gates in CI; puzzle fairness 100 % over 365 days | Ready |
| Deployment | Dockerfile, Cloud Run and Firebase Hosting configs, deploy workflow, [deploy guide](deploy.md) | Untested against a real project |
| Rollback | revision traffic shift plus feature-flag kill switches (documented in the bad-deploy runbook) | Untested live |

## Go / no-go for a trusted-tester launch

**No-go until:** (1) a staging environment exists and the deploy workflow has run once end to end; (2) the privacy notice
and terms are approved; (3) the NVDA/VoiceOver pass is done; (4) S4 (proxy hops) is verified on staging; (5) the
load test is repeated on Cloud Run with the generator on a separate host.

Everything else is in place. These five items are procedural, not engineering gaps, and each has an owner-shaped
instruction above.

## Known limitations to tell testers

- The catalog covers about a hundred seed artists and their credited collaborators, not all of music.
- Importing a 2,000-artist history takes tens of seconds; typical playlists take about a second.
- Rate limits and caches are per instance.
