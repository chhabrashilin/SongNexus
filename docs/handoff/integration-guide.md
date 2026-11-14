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

Audio descriptors and listening aggregates are enrichment seams too: `recording_descriptors` (tempo, key, mood
probabilities) and `artist_audiences` / `artist_colistening` (listener counts, co-listening ranks). YouTube Music
would fill them from its own audio analysis and first-party aggregates, keeping the 50-listener floor
(`core/listening.py`), and re-run `eval-songs` and `eval-listening` against them.

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
Two ways in today. Files are parsed on the device in a Web Worker (`web/src/importers`); only distinct artist names
reach `POST /v1/playlists:analyze`. Linked accounts (R2-6, [ADR 0006](../adr/0006-linked-accounts.md)) sync from
ListenBrainz, Last.fm, Libre.fm, Spotify, Deezer, Apple Music and YouTube Music through one connector interface
(`accounts/connectors.py`: `fetch(http, credentials, cursor) -> Page`) and keep only per-artist tallies.

For YouTube Music, implement `YouTubeMusicFirstPartyAdapter` against the internal history service and register it
in `service/linking.py` in place of `YouTubeConnector` (liked songs through the public Data API). It replaces:
the OAuth flow (the user is already signed in), token storage (no third-party token), name resolution (history
carries catalog IDs, so `resolve_names` becomes an identity map), and Takeout import. Keep: aggregates only, the
sync cadence and backoff, "Sync now" limits, unlink deletes everything, and the export and deletion coverage. The
contract tests in `tests/accounts/test_connectors.py` and `tests/service/test_accounts_api.py` show the expected
behavior.

### 4. Friends and sharing (reuse or replace)
Invite-only friendship, shares with notes, inbox, blocks and reports ([ADR 0007](../adr/0007-friends-and-sharing.md),
`service/routes/social.py`). A YouTube Music build would map display names to the product's own handles and route
reports into the existing trust and safety tooling. Put the production classifier behind
`social/moderation.Moderator` and keep the invariants the tests encode: no discovery without an invite, silent
mutual blocks, limits counted per sender, and erase-on-delete.

### 5. Client (replace)
The web app is a reference client styled with Material 3 tokens. It uses only the public contract: regenerate types with
`npm run api:types`. Feature flags (`GET /v1/config`) switch surfaces off without a deploy.

### 6. Deployment (replace)
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
