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

On Windows, the README's development SQLite database can also be used for these
read-only journeys. Keep the API running on 8790, then in `web/`:

```powershell
npm.cmd run build
npx.cmd vite preview --host 127.0.0.1 --port 4273 --strictPort
# In another terminal, also in web/:
npx.cmd playwright test --workers=2
```

Daily journeys fix the browser calendar to October 8, 2026. They check a wrong
move, solve, source-backed reveal, reload, archive/back navigation, a pending
move across dates, sharing and cancellation. Solved views are scanned in light
and dark themes on both device profiles. Screenshots are written under the
git-ignored `test-results/` directory. If Chromium is not installed yet, run
`npx.cmd playwright install chromium` once.
