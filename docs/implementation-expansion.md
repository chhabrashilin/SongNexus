# Implemented expansion and database migration

## University directory

The directory includes 120 fictional campuses across 40 country codes, alongside the existing Wikidata communities. Every fictional entry carries `synthetic: true`, a `demo-` ID, a visible Demo suffix, and no fabricated official website or Wikidata link. These are interface fixtures, not accredited institutions or enrollment verification.

`GET /v1/communities?kind=CAMPUS&country=JP&synthetic=true` filters by country and provenance. Search matches names, short names, cities, regions and country codes. Pagination tokens are scoped to the filters. The Around you picker has country/demo controls and shows errors separately from empty results.

## Catalog expansion

From server/ (the Python module form also works while a running Windows server locks the installed launcher):

```powershell
.venv/Scripts/python.exe -m songnexus.cli fetch-recordings --artist 83d91898-7763-47d7-b03b-b92132375c47 --limit 100 --output ../data/raw/recordings-new.jsonl.gz
.venv/Scripts/python.exe -m songnexus.cli merge-snapshots ../data/samples/musicbrainz_snapshot.jsonl.gz ../data/raw/recordings-new.jsonl.gz --output ../data/raw/catalog-new.jsonl.gz
.venv/Scripts/python.exe -m songnexus.cli ingest --snapshot ../data/raw/catalog-new.jsonl.gz --with-enrichment
```

Use new output paths each run. Fetch is bounded to 10,000 records per invocation and uses the existing polite cached client. Merge retains old request identities and lets the last input replace a conflicting identity. Ingest retains existing quality gates and, with `--with-enrichment`, includes the configured enrichment snapshots. This is incremental snapshot expansion, not a full-dump importer. Both merge/canonicalization remain memory-bound; importing millions of records requires a separate bulk pipeline.

### Catalog expansion run (2026-11-16)

`fetch-recordings` now accepts `--artist` several times (the limit is per artist) and requests `inc=artist-credits+artist-rels`. Earlier it fetched artist credits only, so producers, engineers, mixers and instrumentalists never arrived with browsed recordings.

- Fetched 600 recordings per artist (or all, if fewer) for the 43 best-connected "full" artists already in the catalog (Beyonce, Drake, Ye, Rihanna, Pharrell, Kendrick Lamar, Quincy Jones, ...): 23,064 recordings in 308 requests, with the polite client, no contact, generic User-Agent. Output `data/raw/musicbrainz-recordings-top45.jsonl.gz`.
- The earlier 100-record fetch was entirely new (none of its keys were in the sample snapshot; the dev DB had been ingested from the sample, 1,732 records). Merge of sample + that + top45 gave 24,896 records, 0 replaced, written to `data/raw/musicbrainz-expanded-2.jsonl.gz`.
- Trial ingest into a copy of the dev DB (`data/raw/scratch-ingest.db`, via `SONGNEXUS_DATABASE_URL`) passed every quality gate (0 violations) with 0 rows garbage-collected or deleted. All old recording/release/label ids and all old recording-credit ids survived; Kendrick Lamar `10851cf2-...` kept its id. Four stub artists only gained type or country.
- The dev DB was then backed up (`data/raw/backups/songnexus-dev-pre-expansion2-20261116T215935.sqlite`) and ingested with `--with-enrichment` (about 5 minutes). Ingest only rewrites catalog tables, raw_records, data_sources and ingestion_runs; user, community and artist_images tables are not touched.

| | before | after |
|---|---|---|
| artists | 5,854 | 11,850 |
| recordings | 4,740 | 17,123 |
| recording credits | 40,949 | 84,254 |
| co-credited artist pairs | 61,429 | 147,900 |
| artist relations | 624 | 624 |

Kendrick Lamar went from 74 to 462 credited recordings. Running servers must be restarted to see the new catalog.

## Database migration

The existing SQLite schema was backed up under `data/raw/backups/` and upgraded from 0007 to 0008. A consistent post-migration SQLite backup was copied to the local Docker PostgreSQL instance on port 15432. All 146,539 rows across 39 application tables were verified; the source was not deleted. API health and synthetic-directory filtering passed against PostgreSQL.

The copy is a snapshot, not replication. The existing SQLite runtime configuration remains in place: changes made after the snapshot are not present in PostgreSQL. Before an actual production cutover, stop source writers, take a final backup, copy to a fresh empty destination, verify, then switch the runtime connection string and restart. Preserve the token encryption keys and Firebase project identity when moving linked accounts/sessions.

```powershell
# Set SONGNEXUS_TARGET_DATABASE_URL securely in the process environment first.
# Credentials belong in local secret configuration, never in Git or chat.
.venv/Scripts/python.exe -m songnexus.cli transfer-database
.venv/Scripts/python.exe -m songnexus.cli transfer-database --apply
```

Default mode only reports table counts. Apply migrates the empty destination and copies in dependency order in one data transaction. Occupied destinations and unrelated tables are refused. PostgreSQL sequences are reset after copying. Schema creation is separate from data copying; a failed copy can leave an empty migrated schema. Keep databases private to the API; do not expose migrated user/session tables through a public data API.

## Cloud activation

User selected new free-tier Firebase and Supabase projects. Neither integration was connected when implementation started. Creation, Google sign-in setup, hosted database migration and deployment require those account connections. No cloud project, paid subscription, or public deployment has been created.

The existing deployment targets Cloud Run and Firebase Hosting and assumes Cloud SQL. Cloud SQL is not the requested free PostgreSQL option: replace that dependency with the Supabase connection secret before deploying. Cloud Run quotas are usage-based and not a promise of a permanently free deployment.

The workflow now supplies Firebase web configuration to the frontend build and fails explicitly when the API key/auth domain are missing. Required values: GCP_PROJECT_ID, VITE_FIREBASE_API_KEY, VITE_FIREBASE_AUTH_DOMAIN, and the existing deployment/WIF settings. Firebase web API keys are public application configuration; database passwords and service-account credentials remain secrets.

Browser visual QA could not run because the browser access host was unavailable. Build and API checks are separate from visual verification.
