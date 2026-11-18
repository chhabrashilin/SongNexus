# Catalog build failure

**Symptom:** `gcloud run jobs execute songnexus-ingest --wait` exits non-zero.

**Impact:** none for users. The quality gate runs inside the ingest transaction, so a failing catalog is rolled back and
the previous catalog keeps serving. `GetConfig.graphVersion` tells you which one is live.

**Triage:** read the job log. `QualityGateError` lists the failed checks (for example a golden fact missing, orphaned
edges, too few artists). Reproduce locally: `uv run songnexus ingest --snapshot data/raw/<snapshot>` then
`uv run songnexus quality`.

| Cause | Fix |
|---|---|
| A new snapshot lost or changed a known fact | inspect the diff against the previous snapshot; fix the adapter or revert the snapshot |
| MusicBrainz fetch failed or rate-limited (`fetch`) | rerun later; the fetch is cached and rate-limited; do not lower the delay |
| Migration not applied | `songnexus migrate`, rerun |
| Advisory lock held | another ingest is running; wait for it |

Never lower a quality threshold to get a build through; fix the data or the rule and record why.
