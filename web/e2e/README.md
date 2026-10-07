# End-to-end tests

Journeys for the committed screens, each with an axe scan (zero serious or critical issues),
on a phone profile (Pixel 7) and desktop Chrome.

```sh
# 1. API on :8790 with the reference catalog (SQLite is fine locally)
cd server
SONGNEXUS_DATABASE_URL=sqlite:///../e2e.db uv run songnexus ingest
SONGNEXUS_DATABASE_URL=sqlite:///../e2e.db \
SONGNEXUS_ALLOWED_ORIGINS='["http://127.0.0.1:4273"]' \
  uv run uvicorn songnexus.service.app:create_app --factory --port 8790

# 2. Production build, served with /v1 proxied to the API
cd web && npm run build && npx vite preview --host 127.0.0.1 --port 4273

# 3. Tests
npx playwright test
```
