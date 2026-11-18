# SongNexus: product strategy and feature roadmap

| | |
|---|---|
| **Status** | Proposal for review |
| **Authors** | SongNexus team (UW–Madison CS 620) |
| **Reviewers** | Google project sponsors |
| **Last updated** | 2026-11-16 |
| **Builds on** | [design-doc.md](design-doc.md) (R1 architecture), [r2-plan.md](../plans/r2-plan.md) (R2 stories), [ytm-design-system.md](ytm-design-system.md) (UI rules) |

## 1. Summary

SongNexus shows the people behind the music and how they connect, with a published credit behind every
line. Inside YouTube Music it is a discovery layer: the place you go after a song to find who made it, who
else they made music with, and what to play next for a reason you can see.

We propose to win one audience first: **college students, launched campus by campus**. Students are the
heaviest music listeners, form taste in groups, and are the audience YouTube Music most needs to convert
(the student Premium plan exists for exactly this reason). Three features give them a reason to come back
and a reason to bring friends: what their campus is listening to, a daily puzzle they can compare, and
connection stories they can share.

## 2. The niche: campus music scenes

### 2.1 Who

| Segment | What they want | What SongNexus gives them |
|---|---|---|
| **Credits-curious students** (core) | Know who is behind the songs they love; sound informed | The connection web, collaborations, song credits, Ask |
| **Campus social listeners** | Belong; compare taste with friends and their school | Around you (campus and city charts), friends, shares |
| **Daily-habit players** | A small daily ritual with bragging rights | Daily puzzle, Credit check, path challenges |
| **Student radio and music clubs** (seed communities) | Content and discovery for their shows | Stories, campus charts, label and producer pages |

### 2.2 Why this niche

- **Concentrated and reachable.** A campus is a closed network: one launch (orientation week, student
  radio, a music club) reaches thousands of people who see each other daily. Word of mouth compounds.
- **Network effects that unlock.** A campus chart appears once 10 students join, which turns joining into
  a shared goal ("UW–Madison needs 7 more listeners") instead of a privacy cost.
- **Commercial fit for YouTube Music.** Students are the Premium student plan's audience; a discovery
  habit formed in college carries into the paid individual plan after graduation.
- **Defensible.** Credit-grounded discovery needs a curated credits graph with evidence. Competitors
  recommend by similarity; we explain by people.

### 2.3 Positioning

> For college students who want to know the people behind their music, SongNexus is the discovery layer of
> YouTube Music that shows how artists connect, with the credits to prove it, and what your campus is
> listening to. Unlike algorithmic recommendations, every suggestion comes with a reason you can check.

## 3. What ships today (R2 + redesign)

| Area | Feature | Status |
|---|---|---|
| Discover | Connection web (cover-art nodes, hover neighborhoods, credits panel, filters, list view) | Shipped |
| Discover | Find a path between any two artists (fewest steps or strongest links), shareable | Shipped |
| Discover | Compare artists (shared collaborators, genres, shared audience from aggregate listening) | Shipped |
| Discover | Compare songs (sound profile and shared credits) | Shipped |
| Discover | Artist, song and label pages; collaborations by type, year and genre | Shipped |
| Discover | **Ask in the search bar**: natural-language questions answered from our data | In progress |
| Discover | **Stories**: a feed of surprising, evidence-backed connections | In progress |
| Social | Friends by invite, sharing with notes, inbox, blocks and reports | Shipped |
| Social | **Around you**: opt-in campus and city charts with minimum group sizes | In progress |
| Play | Daily puzzle (link two artists), archive, local stats | Shipped |
| Play | **Games hub, Credit check trivia, daily path challenges** | In progress |
| You | Linked accounts (YouTube Music, Spotify, Last.fm, ListenBrainz, Deezer, Libre.fm), on-device playlist import | Shipped |
| Platform | **Response caching (memory or Redis), HTTP caching, prefetch on intent** | In progress |

## 4. Growth loops

1. **Campus unlock.** A student joins their campus; the page shows how many more are needed; they share
   the link; the chart unlocks for everyone. Each chart is a reason to return weekly.
2. **Puzzle share.** The daily puzzle and Credit check produce spoiler-free share text; the link lands on
   the same puzzle. Campus leaderboards (below) turn this into friendly competition.
3. **Story share.** A story is a single surprising fact with proof ("these two never released together,
   but share a producer"). It is built to be posted, and the link opens the connection web.
4. **Friend paths.** "How are your top artists connected to mine?" Two friends' libraries joined by the
   shortest paths between them: a reason to invite.

## 5. Feature roadmap

Ranked by impact on the niche against effort. "Fits YouTube Music" means it maps to a surface YouTube Music
already has (now playing, artist page, search, library, sharing).

### 5.1 Next (one milestone each)

| Feature | What it is | Why it matters | Fits YouTube Music |
|---|---|---|---|
| **Campus leaderboards** | Daily puzzle and Credit check scores by campus (opt-in, aggregate, top 10 schools and your rank) | Turns a solo habit into school rivalry; strongest retention lever for the niche | Shared moments, Recap |
| **Now-playing credits card** | A compact card for the song playing: producers, features, one "connected to" suggestion | Puts SongNexus where listening happens instead of a separate destination | Now playing "Credits" tab |
| **Playlists from a path or a web** | Turn a path or a selected neighborhood into a playlist (one track per credit) | Converts discovery into listening time, the metric YouTube Music cares about | Playlists |
| **Friend paths** | Shortest paths between two friends' top artists, with the songs along the way | Social reason to invite; uses data we already have | Sharing, Library |
| **Producer and session-player spotlights** | Pages and shelves for the people behind many records (not only headliners) | Our unique content; nobody else surfaces this well | Artist pages |
| **Weekly campus recap** | A Sunday digest of your campus chart movers and the week's best story | A reason to return weekly; ideal for notifications | Recap, notifications |

### 5.2 Later

| Feature | What it is |
|---|---|
| **Sample chains** | Follow a sample through the songs that used it, across eras, with audio previews where licensed |
| **Concert and tour links** | "Playing near campus" for artists in your campus chart (partner API) |
| **Student radio toolkit** | Embeddable charts and stories for station websites; show-prep packs |
| **Artist and label insights (B2B)** | Aggregate, anonymous campus reach for artists and labels (revenue path; needs legal review) |
| **Collaborative webs** | Build a connection web with friends in real time |
| **Accessibility-first audio tour** | Spoken walk-through of a connection web for screen-reader and eyes-free use |
| **More languages and markets** | The app is internationalized (ICU messages, RTL); add locales with campus launches abroad |

### 5.3 Considered and not now

| Idea | Why not now |
|---|---|
| A chat assistant that writes answers | Risk of confident false claims about artists. Ask interprets questions with a model but answers only from credits. |
| Individual "who on campus listens to X" | Exposes individuals. Charts are aggregate with minimum group sizes only. |
| Scraped streaming data | Against provider terms; we use official APIs and exports only. |
| Short-video "Reels" | No licensed video or audio; Stories delivers the same snackable format from our data. |

## 6. Success metrics

| Metric | Target for a campus pilot (one semester) |
|---|---|
| Campus chart unlocked (≥ 10 members) | 3 pilot campuses within 4 weeks |
| Weekly active / monthly active | ≥ 35% |
| Daily puzzle D7 retention | ≥ 25% |
| Shares per weekly active user | ≥ 0.5 |
| Discovery to listening | ≥ 20% of web/path sessions end in a play or playlist save (needs YouTube Music integration) |
| Trust | < 1% of evidence reports confirmed wrong |

All targets are proposals to validate in the pilot; none are measured yet.

## 7. Performance commitments

| Interaction | Budget |
|---|---|
| Search suggestions | p95 < 150 ms server time |
| Open an artist or a connection web | p95 < 300 ms server time warm, < 1 s cold |
| Find a path | p95 < 500 ms warm |
| Ask (parser) / Ask (with model) | p95 < 200 ms / < 4 s, with a parser fallback |
| Initial JavaScript | < 200 KB gzip (currently 142 KB) |

Caching strategy: responses keyed by graph version (so a data refresh invalidates everything at once),
in-process by default, Redis (Memorystore) when running more than one instance; ETags and short public
cache lifetimes for anonymous catalog reads; prefetch on hover and focus in the client. Measured results
are recorded in [measurements.md](../perf/measurements.md).

## 8. Risks

| Risk | Mitigation |
|---|---|
| Campus charts never reach the threshold | Seed with student radio and music clubs; show progress and make the invite one tap |
| Privacy perception of campus membership | Opt-in only, one-tap leave, minimum group sizes, plain-language explanation on the page |
| Free-tier model limits or outages for Ask | Deterministic parser handles common questions; the model is optional and cached |
| Credits coverage gaps for new releases | Show "not in our data yet"; ingest updates; let users report gaps |
| Dependence on YouTube Music integration for listening metrics | Linked accounts and imports work today; integration plan in design-doc §11 |

## 9. Open questions for the sponsor

1. Can a pilot run under a YouTube Music experiment flag on campus, or should it run as a standalone web app first?
2. Is the student Premium plan's conversion the right north-star business metric for the pilot?
3. What review is needed before campus-level aggregates are shown, and what minimum group size does Google's privacy review expect (we use 10 members per chart and 3 listeners per row)?
4. Which free or internal model should Ask use inside Google (the reference build supports the Gemini API free tier, OpenRouter free models and local Ollama)?
