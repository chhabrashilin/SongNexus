# ADR 0004: Daily puzzles use a deterministic shuffled cycle

Status: implemented on `v2`; review pending.

## Context

Hashing the date modulo the number of fair pairs can repeat yesterday's puzzle
while leaving other pairs unused. The exported Daily v2 patch fixes this in the
prototype, but that code targets `bb75be8` and cannot be applied to the current
`server/` and `web/` architecture.

## Decision

Adapt the behavior to the current pure game core and resource-oriented API.
Keep the v2 launch date, October 7, 2026, and its local-calendar-day rule.

Enumerate sorted, unordered pairs of fully loaded artists whose shortest path
is three or four steps. For each cycle, shuffle a copy with a fixed seed derived
from `songnexus-daily-v2` and the cycle number. Divide the number of days since
launch by the pair count to choose the cycle and position. Date-derived
orientation varies which artist starts without changing pair uniqueness.

The pure core keeps a bounded cache of 16 schedules. Catalog-specific candidate
pairs remain in the read-model memo (one entry per catalog). Nothing mutates the
candidate list or relies on Python's randomized `hash()`.

## Consequences

- For a fixed catalog, every candidate pair appears exactly once per cycle.
  A pair can repeat across a cycle boundary.
- All clients get the same puzzle for a given calendar date and catalog.
  `/play` follows the viewer's local date; `/play?date=YYYY-MM-DD` stays on that date.
- A catalog change can change historical puzzles. Saved progress includes date,
  graph version, ordered endpoints and par, and only resumes the exact puzzle.
- Old single-slot progress is left untouched but not replayed against the new
  schedule. New progress uses `songnexus.play.v2` and retains one game per date.
- Streaks count consecutive puzzles won on their own local day. Archive wins
  count toward totals, never toward streaks. Giving up today ends a streak;
  leaving today's puzzle unfinished preserves yesterday's streak until midnight.
- This does not create a permanent historical catalog or a curated puzzle store.
  Those require a separate persistence decision if archive stability becomes a
  product requirement.

## Verification

Property tests compare fairness and hints with NetworkX. Schedule tests traverse
complete cycles, ignoring orientation. API tests exercise moves, reveal,
canonical dates and share reporting. Web unit tests cover storage, calendar
boundaries, stats and legacy links; browser journeys cover solving, archive
navigation, reloads, pending requests and successful/cancelled sharing.
