# Demo script (about ten minutes)

Setup (once): `cd server && uv sync && uv run songnexus ingest`, then `uv run songnexus serve` (API on :8790) and in
`web/` `npm ci && npm run dev` (app on :5173). Without Firebase configuration, development offers "Sign in
(development)"; open the app with `?listener=ana` in one browser and `?listener=ben` in another (or a private
window) to be two people for steps 10–11.

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
| 9 | "Bring your listening." | You: Connected services; connect ListenBrainz with a user token, then Sync now | Per-artist counts only; "synced N minutes ago", never "real time"; Disconnect deletes it all |
| 10 | "Friends join only by invite." | As Ana: Friends, pick a name, Create an invite, copy the link. As Ben: open it, accept | No search or contacts; single-use code that expires |
| 11 | "Share with a reason." | As Ana: an artist page, Share with a friend, add a note. As Ben: the badge, the inbox, Open; Library shows "From your friends" | Moderated note, read state, block and report on every share |
| 12 | "Where it falls short." | Open `docs/handoff/limitations.md` | Budgets missed or unverified, recorded |

Rehearsal checklist (run twice before presenting): fresh ingest, API and web start cleanly, each step above, then the
`?locale=ar-XB` and `?locale=en-XA` pseudo-locales on Home. Record any deviation in this file.

Rehearsals so far: none with an audience. Steps 1–8 were exercised by the automated browser journeys on 2026-10-13.
