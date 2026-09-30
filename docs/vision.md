# Vision: from a graph tool to a global daily ritual

## The problem with "explore the graph"

People don't wake up wanting to explore a knowledge graph. They want to **play, share, and listen**. The
capabilities we've built (true, cited connections between any two artists) are exactly what a mass-market product
needs. The *interaction* has to change: the graph should be the engine under a habit, not the screen people land on.

**Thesis: SongNexus becomes the daily ritual of music discovery.** Every play teaches something true about music,
and every claim is cited. In a web filling with unsourced AI answers, "every link has a receipt" is the identity.

## Bet 1 (built): SongNexus Daily

One puzzle a day, the same for everyone on Earth: *"Get from Metro Boomin to Mac Miller."* You name artists who
worked directly together, one step at a time. Every correct step reveals the real credit
(*"John Mayer produced Travis Scott's 'ASTROTHUNDER'"*) and how many steps remain. Solve it, then share a
spoiler-free card:

```
SongNexus Daily #1 🎧
Metro Boomin → Mac Miller
3 steps (par 3) · 1 miss · 1 hint
🟩🟩🟩🎯
```

Why this can go global:
- **Five-second rules**, no graph literacy needed, fun at any level of music knowledge.
- **A built-in growth loop:** the share card creates curiosity among people who haven't played, the same mechanism
  behind Wordle and NYT Connections (which the Google brief names as inspiration).
- **It teaches instead of quizzing:** wrong guesses cost nothing, and right guesses deliver a verified fact. You finish knowing
  more music than you started with.
- **It's cheap to run:** deterministic graph lookups, no LLM per move, and puzzles chosen from the date, so no
  content team is needed.
- **It showcases the engineering:** fair-puzzle generation (distance 3–4 between well-known artists),
  bidirectional-BFS "warmer/colder" feedback, and hints guaranteed to contain a step closer.

What's in the prototype: `GET /game/daily`, `POST /game/check`, `GET /game/hint`, `GET /game/solution`, a Play
mode with a chain board, warmer/colder distances, hints, undo, give up, share (the native share sheet on phones,
clipboard elsewhere), and progress that survives a reload. The sample graph yields **109 fair puzzles**; the full
dataset (Bet 5) makes that effectively unlimited.

**Next for Daily:** streaks and an archive; difficulty tiers (Easy: famous intermediaries only; Hard: par 5);
share images that show start and target but never the route; regional editions (K-pop, Afrobeats, Latin,
Bollywood, jazz); global leaderboards (needs server-side sessions and anti-cheat, since progress is client-side today).

## Bet 2: Liner notes for the streaming era

Streaming killed the liner notes. **Share any song link from Spotify, YouTube or Apple Music to SongNexus** (share
sheet, browser extension, or paste) and get the people behind it (producers, players, samples) plus how they
connect to everything else you love. Technically: resolve link → ISRC or URL relationship → MusicBrainz
recording, then our graph. This turns every listening moment into an entry point, with zero search needed.

## Bet 3: Your music universe (Wrapped, all year)

Import listening history: **ListenBrainz first** (open and CC0), or a Spotify data-export file processed
entirely in the browser for privacy. Then show a personal graph: *"You're 3 steps from Herbie Hancock,"* *"the
producer behind 9 of your top 50 songs,"* *"the session drummer your favorite artists all share."* Every insight is
shareable, and every insight is cited.

## Bet 4: The open-data flywheel

We don't own music data; we amplify the open commons. When the game or a path search finds a *missing link*
("these two definitely worked together, but the data doesn't show it"), we invite the user to add the credit to
MusicBrainz, which every other open music project then benefits from. Players become contributors, and the dataset
behind SongNexus (and much of the open music web) gets better every day. This is the story that makes SongNexus
bigger than an app.

## Bet 5: Global by default

Scale from 28 seed artists to the **full MusicBrainz and Wikidata dumps** (millions of artists, CC0), with
multilingual names already in the data (방탄소년단, Бьорк) so search works in any script. Regional seed sets make
"How is BTS connected to Bad Bunny?" answerable. The architecture already anticipates this path (ADR-001's
scaling triggers, Phase 1 cross-source entity resolution).

## Bet 6: Embeddable connections

An oEmbed/iframe card ("How Daft Punk connects to Kamasi Washington", each step cited) for music journalists,
newsletters and fan wikis. Every embed is a distribution channel.

## Risks we're taking, and how we'd know

| Risk | Mitigation / signal |
|---|---|
| Daily doesn't stick | Measure D1/D7 return, completion and share rate (aggregate counters only). If D7 stays low after 4 weeks of iteration, lead with Bet 2 instead |
| Puzzles route through obscure engineers and session players | Default categories already exclude engineering; add an "Easy" tier restricted to well-known artists; tune using give-up rates |
| Audio and cover art licensing | Don't host audio; link out to streaming services. Cover Art Archive images carry per-image rights, so show them only where permitted |
| Cheating on global leaderboards | Leaderboards only after server-side game sessions; the casual game can tolerate client-side progress |
| Scale costs | The read model is cheap; the game is deterministic and cacheable per day; LLM features stay optional |
| Data gaps read as "no connection" | Already handled with honest wording everywhere; Bet 4 turns gaps into contributions |

## Sequencing

1. **Now:** Daily prototype (done) → team playtest → share with classmates for a week and watch completion and share rate.
2. **Phase 1 data scale-up** is the unlock for everything else (bigger graph = more puzzles, more surprising links, global coverage).
3. Bet 2 (liner notes) next, since it needs no accounts; Bet 3 once privacy-preserving import is designed; Bet 4 as
   soon as "missing link" moments are frequent enough to matter.
