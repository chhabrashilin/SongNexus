# Daily puzzle on v2

The Daily v2 behavior is integrated into `server/` and `web/`. The original
22-file patch targets the prototype at `bb75be8`; do not apply it to this branch.
The v2 package already uses its local README, so no packaging workaround is needed.

## Playing and sharing

- `/play`: today's puzzle, using the viewer's local calendar date.
- `/play?date=2026-10-07`: a specific day's puzzle. The archive starts October 7,
  2026 and ends today; unavailable dates show a notice and today's puzzle.
- Explore remains `/explore/:id`; connections remain `/six-degrees?from=<id>&to=<id>`.
  Browser back/forward navigation preserves these views.
- Prototype root links (`?play=`, `?tab=play`, `?artist=`, `?from=&to=`) redirect
  into the equivalent v2 screen. The retired Ask screen is not restored.

Correct moves include evidence and warmer/colder feedback. Hints always include
a closer eligible neighbor, or return no candidates when that is impossible.
Empty hints do not consume a hint. Blocked artists are excluded from suggestions.

Progress is local to the device and keyed to the actual puzzle, as described in
[ADR 0004](adr/0004-daily-puzzle-schedule.md). Stats show finished games, win rate,
wins at par or better, current streak and best streak. Storage being blocked or
full does not prevent playing, but that visit's progress may not survive reload.

Share cards contain endpoints, result, move colors and a dated link; intermediate
artists never appear. A successful native share or clipboard copy triggers a
best-effort aggregate event. Cancellation and failed copying do not. Reporting
failure never prevents sharing.

## API

The generated [OpenAPI contract](../server/openapi.json) is authoritative.
Methods are anonymous and use the existing analysis rate limit.

| Method | Resource | Purpose |
|---|---|---|
| GET | `/v1/puzzles/{date}` | Start, target, number, par and graph version |
| POST | `/v1/puzzles/{date}:checkMove` | Check `{fromArtist, toArtist}` resource names |
| POST | `/v1/puzzles/{date}:hint` | Suggest candidates from `{fromArtist}` |
| GET | `/v1/puzzles/{date}:reveal` | Shortest route with credits and sources |
| POST | `/v1/puzzles:share` | Report a share action, no body, HTTP 204 |

Dates must be canonical `YYYY-MM-DD`, from launch through UTC today + 1 to
accommodate UTC+14 clients. Invalid dates return the common INVALID_ARGUMENT
error. Puzzle availability depends on the loaded catalog.

Each share action emits a structured `metric=game.share, value=1` log event.
Aggregate these events across instances in Cloud Logging; no user, puzzle date,
or result is recorded in the event. This is a count of reported actions, not
unique players or confirmed recipients. Ordinary request logging and rate
limiting still apply. No separate in-memory metrics API is introduced.

## Checks

Run the full checks in the repository README. Focused tests:

```powershell
cd server
uv run pytest tests/core/test_game.py tests/service/test_play.py
cd ../web
npm.cmd test -- src/play/game.test.ts src/app/legacyLinks.test.ts
npx.cmd playwright test --grep 'puzzle|giving up|archive|shares' --workers=2
```

Browser journeys require the API and production preview described in
[the browser test runbook](../web/e2e/README.md).
