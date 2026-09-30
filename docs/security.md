# Security

Academic project, professional defaults.

## Secrets

- No secrets in the repository. `.env` is git-ignored; `.env.example` documents every variable with empty
  values. `ANTHROPIC_API_KEY` is read by the SDK from the environment and never logged.
- The admin reload endpoint is **disabled unless** `SONGNEXUS_ADMIN_TOKEN` is set. It compares with
  `hmac.compare_digest` and answers 404 (not 403) when disabled or wrong, so its existence is not advertised.
- The MusicBrainz contact used in the User-Agent is configurable and empty by default; no personal contact
  details are hard-coded.

## Input handling

- Every endpoint validates inputs with Pydantic/FastAPI: UUID patterns for IDs, length limits on queries and
  questions, enumerations for modes/metrics/categories, numeric bounds on limits and depths.
- All SQL goes through SQLAlchemy with bound parameters; no string-built SQL.
- Hard caps on work per request (neighbors ≤ 150, path depth ≤ 8, alternatives ≤ 5, agent steps ≤ 8, tool
  results ≤ 12k characters) bound CPU and memory.
- Errors return a generic message for unexpected failures (details only in server logs, correlated by request ID).

## Agent safety

- **Allow-listed, read-only tools only.** No SQL, shell, filesystem, network or write access is reachable from the
  model. Unknown tool names and invalid arguments are rejected and traced.
- **Prompt injection awareness:** external text (artist names, titles) reaches the model only as JSON tool
  output. It is sanitized (control characters removed, lengths bounded), and the system prompt declares tool output
  to be data, never instructions. Because tools are read-only and structured response fields come from the ledger,
  the worst case of a successful injection is misleading prose, which the grounding check is designed to flag.
- Per-client rate limiting on `/agent/query` (in-memory token bucket). Client addresses are held in memory only,
  never logged or persisted. Multi-replica deployments need a shared limiter (Redis).

## Transport and browser

- CORS allows only configured origins (`SONGNEXUS_CORS_ORIGINS`), methods GET/POST, and specific headers.
- In Docker, nginx serves the UI and proxies `/api` on the same origin, sets `X-Content-Type-Options: nosniff` and
  `Referrer-Policy: no-referrer`, and external links open with `rel="noreferrer"`.
- The backend container runs as a non-root user.

## Dependencies

CI runs `pip-audit` and `npm audit --audit-level=high` on every pull request. Versions are floor-pinned in
`pyproject.toml`; `package-lock.json` pins the frontend.

## Privacy and analytics

No accounts and no user identifiers. The metrics endpoint aggregates counters (searches, empty results, path
found/not found, graph expansions, agent intents and fallbacks), with no query text, IP addresses or cookies. If
per-query analytics are added (e.g. to mine empty-result queries), they must be stored without IPs and with a
retention limit, and documented here first.

## Data ethics

Only musical relationships are imported. Personal-life relations present in the source (marriage, family) are
deliberately excluded ([data-model.md](data-model.md)).
