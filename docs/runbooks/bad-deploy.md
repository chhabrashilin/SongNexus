# Bad deploy

**Confirm:** the burn-rate alert started within minutes of a release; `gcloud run revisions list --service songnexus-api`
shows traffic on the new revision; logs filtered on `severity>=ERROR` share one exception or route.

**Mitigate (seconds):**
1. Shift traffic back: `gcloud run services update-traffic songnexus-api --region REGION --to-revisions=PREVIOUS=100`.
2. If one surface is at fault and a rollback is not wanted, switch it off: set `SONGNEXUS_FLAGS='{"play": false}'`
   (flags: `play`, `playlistImport`, `labelMates`); the web app hides the surface when `GetConfig` says so.
3. If the release included a migration, do **not** roll the schema back. Migrations are expand/contract, so the previous
   revision still works against the new schema.

**Follow-up:** reproduce with the same image digest locally (`docker run`, see deploy.md), add a regression test, fix
forward, promote the same digest through staging again.

**Latency instead of errors:** compare `latencyMs` by `route` in the request log; a new hot route usually means a missing
cache (`ReadModel.memo`) or an unbounded input. Roll back first.
