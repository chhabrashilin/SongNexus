# Integration guide

How the pieces fit, and what a YouTube Music team would change. Nothing here has been tried against Google systems; each
step names the evidence that proves it works on your data.

## Architecture in one picture

```
 client (web/)  ──HTTP, openapi.json──▶  service  ──▶ read model (in-memory graph, per catalog version)
                                            │                    ▲
                                            ▼                    │ built from
                                  storage (SQL: catalog, users)  ◀── catalog ingest (quality gate in the transaction)
                                            ▲
                          identity (ID token → session)        core (pure logic: graph, search, resolution, puzzle)
```

Layering is enforced in CI (`lint-imports`): `core` imports nothing else from the project, nothing imports `service`.

## The seams

### 1. Catalog (replace)
Today: MusicBrainz snapshots → `catalog/musicbrainz/` parsers → `catalog/canonicalize.py` (`build_batch`) → a
`CanonicalBatch` of typed rows (artists, aliases, releases, recordings, credits, relations, genres, labels, source
mappings) → `catalog/ingest.py` writes it.

To integrate: write a new adapter that produces the same `CanonicalBatch` from your catalog and knowledge graph. Keep:
- deterministic IDs (a pure function of the source ID), so re-ingest is idempotent and links stay stable;
- source-scoped sync (facts attributed to a source are exactly that source's current facts);
- the quality gate inside the transaction (`catalog/quality.py`): a failing catalog is rolled back and never served.
Prove it with: `songnexus quality` (15 checks), the golden tests pattern in `tests/catalog/test_golden.py`, and the
search and import evaluations on your own labeled set.

Genres are a separate seam (`catalog/enrich.py`): a vocabulary (today the MusicBrainz genre list), per-source
artist-genre votes, and parent links between genres. YouTube Music would supply its own genre taxonomy and
associations as one more source; the read model averages shares per source and `SONGNEXUS_GENRE_SOURCES` chooses
which sources are served. Measure agreement with `songnexus eval-genres` before switching.

### 2. Identity (replace or reuse)
Today: Google Sign-In through Firebase Auth; the server verifies the ID token and issues its own HttpOnly session cookie
with a CSRF token (ADR 0002). `identity/tokens.py` defines the verifier interface; swap in Google's internal identity.
Keep the session, CSRF and Origin checks, and the per-user rate limits. The age confirmation and the account deletion and
export methods are part of the privacy design.

### 3. Listening history (replace)
Today the user supplies a file and it is parsed on the device in a Web Worker (`web/src/importers`); only distinct artist
names reach `POST /v1/playlists:analyze`. A YouTube Music implementation would use the user's own history inside the
product and send artist IDs instead of names, which removes the entity-resolution step. Keep the privacy rule: aggregates
only, never logged.

### 4. Client (replace)
The web app is a reference client styled with Material 3 tokens. It uses only the public contract: regenerate types with
`npm run api:types`. Feature flags (`GET /v1/config`) switch surfaces off without a deploy.

### 5. Deployment (replace)
`deploy/` and `docs/deploy.md` describe Cloud Run, Cloud SQL and Firebase Hosting. They are untested against a real
project (see the launch review).

## What to reuse unchanged

- `core/graph`: connection strength, shortest and alternative paths, comparison, collaborations, and explanations (message IDs plus facts, so the server never formats prose).
- `core/search.py` and `core/resolution.py`: Unicode-aware normalization, trigram plus prefix index, edit-distance ranking,
  and a matcher that is exact for every matched or not-matched decision (property-tested against brute force). The
  matcher is deliberately conservative: homonyms are never auto-matched.
- `core/game.py`: a daily puzzle that is the same for everyone, never repeats a pair within a cycle, and keeps every puzzle
  solvable at par 3–4 between well-documented artists (fairness verified over 365 days).
- The API conventions: AIP-193 errors, opaque page tokens, `:verb` custom methods (they need the `rid` path converter,
  guarded by a test).

## Scaling notes

The in-memory read model holds the whole graph per instance (about 1 s to build for 5,854 artists). At YouTube Music scale
it must become a sharded or external graph service; `core` algorithms take an adjacency mapping, so they can run against
any structure with the same shape. The design doc (§7, alternatives considered) discusses the batch-built sharded adjacency approach. Not implemented.

## Integration checklist

1. Produce a `CanonicalBatch` from your catalog; pass the quality gate.
2. Rebuild the labeled sets (`data/eval`) for your catalog; meet search MRR ≥ 0.95 and import precision ≥ 0.98.
3. Replace identity; keep the CSRF and rate-limit tests green.
4. Run the load test (`server/scripts/load_test.py`) from another host against your deployment; compare with the §23 budgets.
5. Re-run the accessibility, security and privacy reviews against your environment.
