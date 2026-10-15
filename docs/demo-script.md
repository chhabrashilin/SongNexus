# Demo script (about ten minutes)

Setup (once): `cd server && uv sync && uv run songnexus ingest`, then `uv run songnexus serve` (API on :8790) and in
`web/` `npm ci && npm run dev` (app on :5173). Sign-in needs Firebase configuration; every step below works signed out
except step 7.

| # | Say | Do | Proof point |
|---|---|---|---|
| 1 | "Every connection comes from a published credit." | Open Home; search `beyonce`, then `방탄소년단` | Search works across scripts and typos |
| 2 | "Each claim has its evidence one tap away." | Open an artist; tap a collaboration | Evidence sheet with the recording and a source link |
| 3 | "Not connected means not in our data yet." | Open About | The honest limits |
| 4 | "Six degrees, with receipts." | Six degrees: Thundercat → Flying Lotus, then a distant pair | Shortest path, each step explained; copy the link |
| 5 | "See the neighborhood." | Explore an artist; switch to the list view | Canvas graph plus an equivalent list (accessibility) |
| 6 | "The daily puzzle." | Play: make a wrong move, use a hint, solve; open the archive; copy the share card | Same puzzle for everyone; share text has no spoilers |
| 7 | "Your music stays on your device." | Library: drop `web/e2e/fixtures/Playlist1.json` | Parsed locally, only artist names sent; analysis of cohesion and connectors |
| 8 | "Built to be handed over." | Show `server/openapi.json`, `lint-imports`, and the test counts | Contract-first, layered, tested |
| 9 | "Where it falls short." | Open `docs/handoff/limitations.md` | One missed budget, recorded |

Rehearsal checklist (run twice before presenting): fresh ingest, API and web start cleanly, each step above, then the
`?locale=ar-XB` and `?locale=en-XA` pseudo-locales on Home. Record any deviation in this file.

Rehearsals so far: none with an audience. Steps 1–8 were exercised by the automated browser journeys on 2026-10-13.
