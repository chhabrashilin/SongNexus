# SongNexus web

The reference client: React 19 + TypeScript (Google style via `gts`), Vite, TanStack Query and React Router.

```sh
npm ci
npm run dev          # http://localhost:5173, proxies /v1 to the API on 127.0.0.1:8790
npm run lint         # gts (ESLint + Prettier)
npm run typecheck
npm test             # Vitest unit tests
npm run build        # production build; then: node scripts/check-bundle-size.mjs (≤ 200 KB gzip initial JS)
npm run api:types    # regenerate src/api/schema.d.ts from ../server/openapi.json (CI checks it is current)
npx playwright test  # browser journeys with accessibility scans (see e2e/README.md)
```

## Layout

| Path | What |
|---|---|
| `src/api/` | Typed client generated from the API contract; one data hook per method |
| `src/app/` | Shell, routes, theme, error boundary, flags |
| `src/auth/` | Google Sign-In (Firebase, loaded only when signing in) and server sessions |
| `src/components/` | Shared UI: search combobox, filters, evidence, sheets, states |
| `src/explore/` | The connection web (canvas) and its pure graph state |
| `src/importers/` | On-device import: format detection and parsing in a Web Worker |
| `src/i18n/` | ICU message catalog (en-US) and pseudo-locales (`?locale=en-XA`, `?locale=ar-XB` for RTL) |
| `src/screens/` | One module per screen, code-split |
| `src/styles/` | Material 3 tokens (light and dark via `light-dark()`), base and component styles |

## Principles

- Every user-visible string is in `src/i18n/messages.ts`; layouts use logical properties (RTL-safe).
- Every claim has its evidence one tap away; gaps are stated ("not in our data yet").
- Listening files are parsed on the device; only artist names are sent for matching.
- Sign-in configuration is optional locally: copy `.env.example` to `.env.local`.
