# Database unavailable

**Confirm:** `/healthz` still answers (liveness) but user, session and `GetArtist` methods return 5xx; logs show
connection or timeout errors from SQLAlchemy; Cloud SQL instance status in the console.

**What still works:** catalog search, paths, compare, puzzles and playlist analysis run from the in-memory read model and
do not need the database. Only sign-in, user data and artist details (aliases, links, sources) fail.

**Mitigate:**
1. Check the instance (maintenance window, storage full, connection limit). Restart it if it is stuck.
2. A connection storm: lower `max-instances` on the service (the pool is 10 + 5 overflow per instance) and redeploy.
3. Corruption or loss: restore from the daily backup or point-in-time recovery to a new instance, update the
   `songnexus-database-url` secret, redeploy. The catalog is rebuildable from the committed snapshot (`songnexus ingest`);
   only user accounts and preferences need the backup.

**Follow-up:** verify a restored database with `songnexus quality` and a sign-in; record the data-loss window, if any.
