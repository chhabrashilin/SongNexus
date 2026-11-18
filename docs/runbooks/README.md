# Runbooks

Each runbook gives the symptom, how to confirm it, the fastest safe mitigation, and the follow-up. Commands assume the
setup in [deploy.md](../deploy.md); replace `REGION`. Mitigate first, diagnose second. Anything lasting over 30 minutes
during demo weeks gets a blameless postmortem.

| Runbook | Symptom |
|---|---|
| [Bad deploy](bad-deploy.md) | error or latency burn alert right after a release |
| [Database unavailable](database-unavailable.md) | `/healthz` fails, 5xx on session and user methods |
| [Auth misconfiguration](auth-misconfiguration.md) | sign-in fails for everyone, or the service refuses to start |
| [Catalog build failure](catalog-build-failure.md) | the ingest job exits non-zero |
| [Quota or abuse](quota-exhausted.md) | surge of 429s, or a Google API quota error |
| [Linked-account sync failures](sync-failures.md) | links stop syncing, "Reconnect" everywhere, or linking fails |
| [Abuse reports](abuse-reports.md) | reports arrive, harassment, or repeated share-limit hits |
