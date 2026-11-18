# Service level objectives and alerting

Targets are for the demo/staging environment (plan §18). They are definitions to be configured in Cloud Monitoring once a
GCP project exists; nothing here is deployed yet.

## SLIs and SLOs (28-day window)

| SLI | Good event | SLO |
|---|---|---|
| Availability | response status is not 5xx (requests that fail before the app, such as load balancer errors, count as bad) | ≥ 99.5 % |
| Latency | request finished within its budget (search 50 ms, entity reads 100 ms, path/compare/move 150 ms, playlist analysis 1.5 s) | ≥ 95 % |
| Catalog freshness | the serving catalog passed the quality gate and is ≤ 35 days old | always |

The error budget for availability is 0.5 % of requests (about 3.4 hours of total outage per 28 days).

## Alerts (multi-window burn rate)

| Alert | Condition | Action |
|---|---|---|
| Fast burn (page) | error rate > 14.4 × budget over 1 h **and** over 5 min | follow the runbook for the failing symptom |
| Slow burn (ticket) | error rate > 6 × budget over 6 h **and** over 30 min | investigate the same business day |
| Latency burn (ticket) | < 95 % of requests within budget over 1 h | check the latency runbook section in [bad deploy](../runbooks/bad-deploy.md) |
| Uptime | `/healthz` fails from 2 regions for 3 minutes | page |
| Auth failures | share of 401 on `POST /v1/sessions` > 20 % for 15 min | [auth misconfiguration](../runbooks/auth-misconfiguration.md) |
| Rate limiting | 429s > 5 % for 15 min | check for abuse or a client retry loop |
| Cost | $25 / month budget alert at 50, 90 and 100 % | review Cloud SQL tier and instance count |

Error-budget policy: when an SLO's budget is spent, feature work pauses for reliability fixes until it recovers.

## What the service emits today

- JSON logs on stdout with `severity`, `message`, `requestId` and request fields (`songnexus.logs`). Cloud Logging maps
  `severity` natively. Request bodies, tokens, cookies and listening data are never logged (tests assert this).
- `GET /healthz` (liveness) and the `X-Request-Id` response header for tracing a single request.
- Not yet built: OpenTelemetry tracing and custom metrics. Log-based metrics on `status` and `latencyMs` cover the SLIs
  above until then. Verify the log fields against a real Cloud Run deployment before relying on the alerts.
