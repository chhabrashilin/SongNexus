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
