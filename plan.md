# SongNexus v2: master plan (temporary)

> **Temporary working document.** Analyze it as a team, settle the decisions in §6, then move what survives into
> `docs/design/design-doc.md`, ADRs and the issue tracker, and delete this file.
>
> **Revision 3 (2026-10-07).** Covers all 18 backlog stories (US-01 to US-18). Changes since rev 2:
> - R1 split into committed / target / stretch tiers, with capacity math and a buffer
> - testable acceptance criteria and a traceability matrix
> - personas, goals and success criteria
> - UX research plan, operations (environments, SLOs, rollback, cost) and a launch process
> - data classification, a dependency license audit
> - fixes: the campus privacy budget, two schedule dependency bugs, reconciliation with the design doc's user journeys
>
> Several stories reverse design-doc non-goals (accounts, social, leaderboards). Update the design doc once this plan is agreed.

**How to read this.** Everyone: §1–6. PM/UX: §7–11. Engineers: §12–24. Leads: §25–33.

| Part A: Product | Part B: Engineering | Part C: Execution |
|---|---|---|
| 1 Summary · 2 Problem and users · 3 Goals and success criteria · 4 External limits · 5 Story map · 6 Decisions | 12 Architecture · 13 Foundations · 14 API · 15 Data · 16 Algorithms and ranking · 17 Scale and capacity · 18 Environments and operations · 19 Security · 20 Privacy · 21 Testing · 22 Metrics and experiments · 23 Performance budgets · 24 Dependencies and licenses | 25 Team and governance · 26 Release plan and capacity · 27 Milestones and changes · 28 Schedule · 29 Traceability · 30 Risks · 31 v0 reuse · 32 Scope control · 33 Analysis questions |
| 7 Requirements per story · 8 UX principles and content · 9 Screens, flows and states · 10 Accessibility and i18n · 11 UX research | | Appendix: glossary |

---

# Part A: Product

## 1. Summary

**What.** A music-connections experience designed for YouTube Music. It shows who made the music, how artists
connect, and how a listener's own music fits together. Every connection is backed by a cited credit.

**Scope.** 18 backlog stories → 9 screens ("surfaces") → 8 shared foundations.

**Delivery** is staged:
- **R1:** the semester demo (week of 2026-12-07), split into committed / target / stretch tiers.
- **R2:** continuation or handoff.

**Deliverables:** design doc, portable core library, service API, mobile-first reference web client styled after
YouTube Music, data pipelines, evaluation sets and results, handoff package.

**Hard constraints:**
- no access to YouTube Music's internal data or APIs;
- no LLM in v1;
- personal data only with consent, minimized, exportable and deletable;
- every change meets `docs/engineering-standards.md`.

**Starting point:** branch `v2` (data assets + design doc + standards). The prototype is at tag `v0-prototype`.

## 2. Problem and users

**Problem.** Credits (who produced, played on, featured on or sampled a song) are scattered across releases and
databases, and streaming apps mostly hide them. Listeners who want to understand *why* music sounds the way it does,
or to discover through the people behind it, have no good way to do it. Recommendations exist, but they rarely say
*why*.

**Personas** (derived from the 18 stories; to validate in UX research, §11):

| Persona | Who | Wants | Stories |
|---|---|---|---|
| **Curious student** | college listener, plays on a phone between classes | fun, surprising facts; what's popular on campus | US-03, US-06, US-02, US-11, US-15 |
| **Competitive fan** | knows a lot, likes to prove it | challenges, badges, beating friends | US-04, US-13, US-09 |
| **Deep listener / curator** | builds playlists, reads credits | depth: credits, comparisons, genre and mood control | US-01, US-05, US-10, US-12, US-14, US-16 |
| **Daily streamer** | listens every day, across services | a feed that keeps it fresh; control over what's shown | US-07, US-08, US-17, US-18 |

## 3. Goals and success criteria

**Product goals**
- **G1 Understandable:** non-experts can find and understand a connection without help.
- **G2 Trustworthy:** 100% of connections shown are backed by a stored fact, with the source one tap away.
- **G3 In control:** users decide what's stored, what's shown (filters, blocks) and who sees it.
- **G4 Adoptable:** the core logic ports to YouTube Music without depending on our stand-ins.

**Non-goals (R1):** audio playback or hosting; social features; LLM features; complete catalog coverage; native mobile
apps (the web client is mobile-first); recommendation ranking learned from data.

**Semester objectives and key results.** These are *targets*: record actuals and don't edit targets afterwards.

| Objective | Key results |
|---|---|
| **O1 Ship R1-committed at production quality** | KR1 every committed story passes its acceptance tests, E2E and accessibility checks · KR2 zero open critical/high security findings at launch review · KR3 every latency budget met in the load test · KR4 CI on `v2` green for the final 2 weeks with no quarantined tests |
| **O2 Show listeners value it** | KR1 ≥ 80% task success on "find how two artists connect" (usability round 2, n ≥ 8) · KR2 System Usability Scale ≥ 75 · KR3 ≥ 70% of testers who start the daily puzzle finish it · KR4 ≥ 90% of testers' real export files import successfully |
| **O3 Make it adoptable** | KR1 sponsor reviews the handoff package · KR2 the core library has zero I/O dependencies (enforced) and ≥ 90% line coverage · KR3 every ranking or matching step has an evaluation set with a recorded result |

## 4. External limits (verify each before building on it)

| Limit | Affects | Plan | Verify by |
|---|---|---|---|
| No public YouTube Music API; the public YouTube Data API doesn't expose listening or watch history | US-07, US-08, US-11 | Import via Google Takeout; native inside Google | M0 |
| Spotify removed audio features, audio analysis, recommendations and related artists from its Web API for new apps (Nov 2024) | US-01, US-14, US-15 | Use AcousticBrainz audio descriptors (CC0) instead | M0 |
| Spotify's developer terms likely restrict use in a competing service; development-mode apps are limited to a small allow-list of users | US-08 | **Legal review.** Prefer user data exports (portability), Last.fm or ListenBrainz sync | before M12 |
| MusicBrainz core data is CC0, but tags/genres/ratings may be licensed **non-commercial** | US-12, US-05; v0's album selection used ratings | Fine for the capstone; a YouTube Music integration needs Google's own genre data. Isolate behind the catalog adapter | M1-09 |
| AcousticBrainz stopped collecting data in 2022 (frozen dataset) | US-01, US-14, US-15 | Show coverage; Google would use its own audio models | M13 |
| YouTube Music Takeout playlists export video IDs, not artist names (verify columns) | US-10 | Look up titles and channels via the YouTube Data API (API key; default quota ~10,000 units/day; a video lookup costs 1 unit per call of up to 50 IDs) | M6 |
| University human-subjects rules may apply to usability testing | §11 | Ask the instructor whether IRB review or a consent form is required | week 1 |

## 5. Story map

### 5.1 Surfaces

| Surface | Stories | Tier (R1) |
|---|---|---|
| **S1 Explore**: expandable connection web + list view | US-02, US-06; filters from US-12 (R1), US-14/15 (R2) | committed (labels: target) |
| **S2 Six Degrees** | US-03 | committed |
| **S3 Compare** | US-05 (R1 target), US-01 (R2) | target |
| **S4 Artist page** (incl. Collaborations) | US-16 | committed |
| **S5 Song page**: credits by role | supports US-01, US-16, track search | target |
| **S6 Play** | US-04 | committed (casual), target (badges, streaks) |
| **S7 For You** | US-07, US-11 | R2 |
| **S8 Library & import** | US-10 (committed), US-08 file imports (target), US-08 sync (R2) | mixed |
| **S9 Profile & settings** | US-18, US-17 (committed), US-09 (target), US-13 (R2) | mixed |

**Reconciliation with the design doc's user journeys:**
- CUJ-1 Credits & connections → S5 Song page.
- CUJ-2 Connect game → S6.
- CUJ-3 Your universe → S7 For You (R2). The R1 import shows a "Your artists" list.
- CUJ-4 Bring your history → S8.
- CUJ-5 Artist connections → S4.

### 5.2 Foundations each story needs

| | F1 Identity | F2 User data | F3 Catalog | F4 Audio | F5 Social | F6 Events | F7 Feed | F8 Import |
|---|---|---|---|---|---|---|---|---|
| US-01 Song comparison | | | ● | ● | | | | |
| US-02/06 Graph / web | | | ● labels | | | | | |
| US-03 Six degrees | | | | | | | | |
| US-04 Gamification | ● | ● | | | ○ friends | ○ | | |
| US-05 Artist comparison | | | ● genres | ○ | | ○ overlap | | |
| US-07 For You | ● | ● | ● releases | ○ | ○ | ● | ● | ○ |
| US-08 Platform connection | ● | ● | | | | ● | | ● |
| US-09 Top 5 | ● | ● | | | ○ | | | |
| US-10 Upload playlist | | ○ | | | | | | ● |
| US-11 Campus | ● | ● | | | | ● | | |
| US-12 Genre | | ○ | ● | | | | | |
| US-13 Friends | ● | ● | | | ● | | | |
| US-14/15 Mood / Energy | | ○ | | ● | | | | |
| US-16 Collaborations | | | ● | | | | | |
| US-17 Block | ○ | ● | | | | | | |
| US-18 Login | ● | ● | | | | | | |

● required · ○ optional or improves it

## 6. Decisions to make first

| ID | Decision | Recommendation | Owner | Blocks |
|---|---|---|---|---|
| D1 | YouTube Music integration path | Handoff package, unless the sponsor offers data/API access in writing | PM + sponsor | F3, US-08 |
| D2 | R1 tiers | As in §26 | PM | everything |
| D3 | LLM in v1 | None; revisit after R1 (Gemini, "rephrase evidence only") | TL | – |
| D4 | License / visibility | Apache-2.0 if the sponsor allows publishing | PM + sponsor | hosting |
| D5 | Languages | Python 3.12 (server), TypeScript (web) | TL | M0 |
| D6 | Storage | PostgreSQL (catalog + user data); SQLite only in unit tests | TL | M1 |
| D7 | JSON naming | lowerCamelCase (Google JSON style) | TL | M3 |
| D8 | UI foundation | Own React components on Material 3 tokens; YouTube Music–like dark theme | UX | M5 |
| D9 | Hosting | Cloud Run + Cloud SQL + Firebase Hosting in a sponsor or team GCP project with a budget alert | TL + PM | M3-08 |
| D10 | Python tooling | uv + lockfile | TL | M0 |
| D11 | Workflow | PRs into `v2`, branch protection, 1 approval, CODEOWNERS | TL | M0 |
| D12 | Identity | Firebase Authentication, Google Sign-In, Firebase session cookies | TL | M4 |
| D13 | Social scope (R2) | Structured shares + optional short note; mutual friends; safety from day one | PM | R2 |
| D14 | Platform connection | R1 file imports; R2 Last.fm/ListenBrainz sync; Spotify after legal review | PM | M6, R2 |
| D15 | Audio descriptors (R2) | AcousticBrainz, with coverage shown | TL | R2 |
| D16 | Catalog completeness | R1 expanded snapshot (~100 seeds, labels, genres); R2 MusicBrainz JSON dumps | TL | M1 |
| D17 | Campus trends (R2) | Opt-in, school-email verification, cohort ≥ 25, differential privacy (§20.4) | Privacy champion | R2 |
| D18 | Real team capacity | Fill in §26.1. If the committed buffer stays under 15%, cut per §32 | PM | everything |

---

## 7. Requirements per story

Format: how it appears, how it's built, API, acceptance criteria (AC) in Given/When/Then, effort in ideal
person-days (pd, including tests), tier. Each AC maps to automated tests (§29).

### US-18 Login: R1 committed · 2 pd (+F1, F2)
- **Appears as:** "Sign in with Google". Profile, preferences, blocks, badges and Top 5 follow the account.
  Settings has sign out (all devices), download my data (target), and delete account.
- **"Can't be manipulated maliciously":**
  - every write is validated on the server;
  - ETags reject stale writes;
  - every resource is authorization-checked;
  - session cookies can't be read by scripts;
  - CSRF protection;
  - an audit log.
- **AC-18.1** Given a signed-out user, when they choose Sign in with Google and complete consent, then a session
  cookie (HttpOnly, Secure, SameSite=Lax) is set and their profile loads.
- **AC-18.2** Given user A's session, when A requests or modifies any `users/B/…` resource, then the API returns
  `PERMISSION_DENIED`, and nothing changes.
- **AC-18.3** Given a preferences update with a stale ETag, then the API returns `ABORTED`, and nothing changes.
- **AC-18.4** Given a signed-in user, when they delete their account, then they are signed out, their data is
  inaccessible immediately and purged within 30 days.

### US-17 Artist block: R1 committed · 2 pd
- **Appears as:** a "Don't show this artist" menu item everywhere; manage the list in Settings; undo via a snackbar.
- **Built as:** stored per user (or locally when signed out). Enforced **server-side** in every read path.
  Blocked artists can't be intermediate steps in paths, but an endpoint the user picked explicitly is allowed. The
  daily puzzle is shared by everyone, so it isn't altered: the user sees a notice and can skip it.
- **API:** `GET/POST/DELETE /v1/users/{user}/blockedArtists/{artist}`.
- **AC-17.1** Given a blocked artist X, when any list-returning endpoint runs (connections, path steps, search
  suggestions, collaborations' "see also"), then X never appears (automated sweep over all endpoints).
- **AC-17.2** Given X blocked, when the user searches for X by name, then X appears with an "Unblock" action.
- **AC-17.3** (stretch, M4-09) Given a signed-out user who blocks X, when they sign in, then X is in their account's block list.

### US-03 Six degrees: R1 committed · 3 pd
- **Appears as:** pick two artists → the chain, animated step by step, with evidence per step; alternative routes;
  "strongest links" mode; respects genre filters and blocks; share link.
- **API:** `GET /v1/artists/{artist}:findPath?target=&mode=&maxSteps=&genres=`.
- **AC-3.1** Given two connected artists within 6 steps, then the shortest chain is shown, and every step shows ≥ 1
  evidence line with a source.
- **AC-3.2** Given no connection within the limit, then the screen says "not connected in our data (yet)", never "not connected".
- **AC-3.3** Given a genre filter or blocks, then no step passes through an excluded artist (property test).
- **AC-3.4** Given a shared link, when opened by anyone, then the same chain is shown (deterministic).

### US-02 Relationship graph and US-06 Connection web: R1 committed · 6 pd (labels: target)
- **Appears as:** Explore → start from an artist → tap a node to expand it; tap a line for its evidence. Toggles for
  producers, features, bands and (target) labels. Breadcrumbs show the expansion path. A list/tree view has the same
  content and is fully keyboard- and screen-reader-navigable.
- **Built as:** force layout rendered to a **canvas** (SVG doesn't hold up past ~300 nodes); a visible-node cap with
  "show more"; "label mates" is a new weak, off-by-default relationship.
- **API:** `GET /v1/artists/{artist}/connections` (filter, pageSize, pageToken, orderBy).
- **AC-2.1** Given an artist, when expanded, then up to 25 strongest connections appear, ordered by strength, with
  "show more" if truncated.
- **AC-2.2** Given 300 visible nodes, then pan and zoom hold ≥ 55 fps on the reference laptop (§23).
- **AC-2.3** Given a screen-reader user, when using the list view, then every node and connection in the graph is
  reachable, with the same evidence.

### US-16 Collaborations: R1 committed · 3 pd
- **Appears as:** Artist page → Collaborations, with tabs: Features (both directions), Co-productions, Bands and side
  projects, Credits for others. Counts, years and evidence for each item. Labeled "based on releases in our data".
- **API:** `GET /v1/artists/{artist}/collaborations?filter=type="FEATURE"&pageToken=`.
- **AC-16.1** Given 3 audited seed artists, then counts per tab match the manual audit exactly.
- **AC-16.2** Given any item, then one tap shows its evidence and source.

### US-10 Upload playlist: R1 committed · 4 pd (+F8)
- **Appears as:** Library → Import playlist → the playlist's artists mapped:
  - how they connect;
  - hidden connectors (people outside the playlist who link its artists);
  - a **cohesion score** (share of artist pairs within 2 steps);
  - "the thread through your mix".
- **Formats (committed):** Spotify `Playlist*.json` and CSV with header detection.
- **Formats (target):** YouTube Music Takeout playlist CSV via video lookup.
- **Formats (stretch):** M3U, TXT, manual column mapping.
- **API:** `POST /v1/playlists:analyze` (stateless; nothing stored unless the user saves it).
- **AC-10.1** Given a supported file, when imported, then parsing happens on the device, and the network request
  contains only track titles and artist names (asserted in E2E by inspecting the request).
- **AC-10.2** Given the labeled set, then artist-match precision ≥ 0.98, with recall reported.
- **AC-10.3** Given an unsupported or oversized file, then the user sees which file and why. No silent drops.

### US-12 Genre selection: R1 committed · 3 pd (+F3 genres)
- **Appears as:** a genre filter (multi-select chips with search) on Explore, Six Degrees and (R2) For You; "stay in genre" for paths.
- **Built as:** an artist matches if the genre's share of its genre votes is ≥ 20% (tunable). Artists with no genre
  data (often producers, the bridges) are allowed by default, behind a toggle.
- **AC-12.1** Given a filter, then no returned artist with genre data falls outside it (property test).
- **AC-12.2** Given the filter UI, then genre-data coverage is shown ("genre known for 71% of artists here").

### US-04 Connection gamification: R1 committed (casual daily puzzle) · 3.5 pd · target (badges, streaks) · 3 pd · R2 (leaderboards, challenges) · 4 pd
- **Appears as:** Play → daily puzzle (v0 rules: link two artists one direct collaboration at a time; warmer/colder;
  hints; spoiler-free share card). Target: badges (*First link*, *On par ×7*, *Bridge builder*, *Genre hopper*) and
  streaks. R2: friend leaderboards and challenges.
- **Built as:** awards are server-authoritative. Ranked play runs in server game sessions (moves validated and
  timestamped; revealing the answer ends the ranked session). Badge rules are declarative and awarded idempotently.
- **AC-4.1** Given any date, then the puzzle is identical for all users, solvable, with par 3–4 (fairness test over every candidate pair).
- **AC-4.2** Given a correct move, then its evidence and the remaining steps are shown. A wrong move reveals nothing.
- **AC-4.3** (target) Given direct API calls out of order or replayed, then no badge is awarded (security test).
- **AC-4.4** (target) Given a user crossing time zones (UTC−12 to UTC+14), then the streak counts by the user's local date without gaps or doubles.

### US-09 Top 5 artists: R1 target · 1.5 pd · stretch (shareable link) · 0.5 pd · R2 (common ground) · 2 pd
- **Appears as:** Profile → pin up to 5 artists (search, or suggested from imported history). Private by default.
  Stretch: a shareable link with a moderated handle. R2: "common ground" with friends.
- **AC-9.1** A 6th artist is rejected server-side (`INVALID_ARGUMENT`).
- **AC-9.2** Private profiles are unreadable by anyone else (authorization matrix).

### US-05 Two-artist comparison: R1 target · 3.5 pd · R2 (listener overlap, audio profiles) · 2 pd
- **Appears as:** Compare → two artists → shared genres (weighted overlap), mutual collaborators with evidence,
  shortest path, collaboration counts by type.
- **AC-5.1** Mutual collaborators exactly equal the intersection of their direct connections (golden tests).
- **AC-5.2** (R2) Listener overlap is shown only when both artists have ≥ 25 consenting listeners; otherwise "not enough data".

### US-08 Platform connection: R1 target (file imports: listening history) · 3.5 pd · R2 (sync) · 6 pd
- **Appears as:** Library → Connected services. R1 walks the user through requesting their Spotify, YouTube Music
  (Takeout) or ListenBrainz export and imports it. Output: "Your artists" (top artists by listening time) and Top 5
  suggestions. R2 adds automatic Last.fm/ListenBrainz sync, and Spotify only after legal review.
- **AC-8.1** Given each supported export format (fixtures), then the top-artist aggregates match the expected output exactly.
- **AC-8.2** Given a 100 MB export, then import finishes in ≤ 15 s and the UI stays responsive (§23).
- **AC-8.3** (R2) Given an unlinked account, then its tokens are revoked and its synced data deleted on request.

### R2 stories (specified now so R1 decisions don't block them)

| Story | Appears as | Built as | Key AC | Effort |
|---|---|---|---|---|
| **US-01 Song comparison** | two songs side by side: shared credits, tempo, key, energy, mood, danceability, artist path | shared credits from the graph; descriptors from F4; "why similar" = the closest 2–3 normalized dimensions + shared people. Song *structure* (sections) needs audio access: out of scope, shown as unavailable | every descriptor shows coverage; shared credits correct on golden pairs | 4 pd |
| **US-07 For You** | explained cards: new collaborations, hidden connectors, path of the day, suggestions, friend shares, campus cards; "Not interested" and "Why this?" | F6 + F7 (§16.6); daily batch per user, topped up on demand | every card has an explanation; blocked artists never appear; offline recall@20 beats a popularity baseline | 4 pd + F6, F7 |
| **US-11 University trends** | "Trending at UW–Madison" card and page | opt-in; email-link verification of a school address; weekly differentially private aggregates; cohort ≥ 25 (§20.4) | below-threshold cohorts return "not enough data"; DP mechanism tests; privacy review sign-off | 5 pd + F6 |
| **US-13 Friend recommendation** | "Send to a friend" on artists, songs, paths and puzzle results; inbox; reactions | F5; structured shares; optional note ≤ 280 characters, screened by a toxicity classifier (e.g. Jigsaw's Perspective API) | blocked users can't send; rate limits enforced; reports reach the review queue | 3 pd + F5 |
| **US-14 Mood / US-15 Energy** | mood chips and an energy slider on Explore and For You, each result showing *why* | F4 scores (§16.5); items without audio data are excluded when filtering, and the count is shown | mood agreement ≥ 0.7 and energy Spearman ρ ≥ 0.6 on a labeled set (targets) | 4 pd + F4 |

## 8. UX principles and content design

**Principles**
1. **Plain language:** no graph jargon ("connection", not "edge").
2. **Evidence one tap away** on every claim.
3. **Honest about gaps** ("not in our data yet").
4. **Mobile first, thumb-reachable.**
5. **Calm motion,** respecting reduced-motion settings.
6. **User in control:** filters, blocks, privacy settings.
7. **Consistent with YouTube Music patterns** (bottom sheets, chips, list rows) without copying its assets.

**Content design.** Sentence case. Numbers as digits. Every empty, error and limitation state gets a dedicated
string in the message catalog; review copy in UX reviews.

| Say | Don't say |
|---|---|
| connection, linked, worked with | edge, node, graph distance |
| credit, credited as | fact, record, relation |
| step(s) apart | hops, degree |
| hidden link (a connector artist) | high betweenness |
| not in our data yet | doesn't exist / not connected |
| strength (explained as "how many credits link them") | weight |

## 9. Screens, flows and states

| Screen | Primary flow | States to design |
|---|---|---|
| Home | today's puzzle card → Play; search; recent artists | first visit, returning, signed in/out, offline |
| Explore (S1) | artist → expand → tap a line → evidence sheet → source | loading, truncated, filter hides everything, error |
| Six Degrees (S2) | pick A, B → animated chain → alternatives → share | not connected, same artist, blocked endpoint |
| Compare (S3) | pick two → overlap sections | no overlap, missing genre data |
| Artist (S4) | header → Collaborations tabs → item → evidence | credits-only artist, empty tab |
| Song (S5) | credits by role → person → artist page | no credits in our data |
| Play (S6) | play → guess → feedback → solve → share | solved, gave up, no route from here, already played, blocked artist in puzzle |
| Library & import (S8) | choose service → export instructions → drop file → results | unsupported, too large, partial match, cancelled |
| Profile & settings (S9) | sign in → Top 5 → blocks → data controls | signed out, delete confirmation, export ready |

The UX lead delivers mocks for every committed screen in week 2. They are reviewed (UX review) before any screen is built.

## 10. Accessibility and internationalization

**Accessibility (WCAG 2.2 AA):**
- keyboard and screen-reader paths for every flow;
- a list equivalent for every graph;
- path animations announced through a live region and skippable;
- the validated color-vision-safe palette (v0), with color never the only encoding;
- 44 px touch targets; focus visible; reduced motion respected.

**Testing:** axe in E2E (zero serious/critical issues) plus a manual NVDA and VoiceOver pass each release.

**Internationalization:**
- Unicode-aware normalization and cross-script alias matching;
- all strings externalized (ICU message format);
- RTL-safe layouts;
- locale-aware numbers and dates;
- R1 ships `en-US` plus a pseudo-locale for testing; other locales are R2.

## 11. UX research

| Round | When | Method | Participants | Questions | Output |
|---|---|---|---|---|---|
| UX-01 Concept test | week 3 | Figma mocks, think-aloud, 30 min | 5 | Do people understand "connections" and evidence? Which surfaces do they want? | changes to the mocks; persona validation |
| UX-02 Usability test | week 7 (staging) | tasks on the built product + System Usability Scale | ≥ 8 | Task success: find a connection, import a playlist, block an artist, play the puzzle | O2 KR1–KR3 measured; issues triaged into P0/P1 |

**Ethics:** confirm with the instructor whether a consent form or IRB review is needed (§4). Record no personal data
beyond the session notes. Participants' own export files never leave their device, and that is demonstrated during the session.

**Recruiting bias:** classmates skew toward CS students. Recruit ≥ 3 non-CS participants per round.

---

# Part B: Engineering

## 12. Architecture

```
web (React/TS) ── HTTPS/JSON ──▶ service (FastAPI, Cloud Run) ──▶ core (pure Python library)
  │ importers (Web Worker)                    │                        ▲
  │ Firebase Auth SDK                         ├──▶ storage (Cloud SQL PostgreSQL)
  └──▶ Firebase Auth ── ID token ─────────────┤
                                              └──▶ jobs (Cloud Run jobs: catalog build, purge, aggregates, feed)
```

**Dependency rules** (enforced by import-linter in CI):
- `core` imports nothing outside itself.
- `catalog` and `jobs` may import `core` and `storage`.
- `service` may import everything.
- Nothing imports `service`.

**Repository layout (end state)**

```
server/  pyproject.toml · uv.lock · alembic.ini
  src/songnexus/ core/ (text, ids, model, graph/, resolution/, search/, explain/, compare/, collaborations/,
                        game/, filters/, playlist/, universe/, feed/)
                 catalog/ (musicbrainz/, acousticbrainz/, ingest, quality)
                 identity/ (token verification, sessions, CSRF, policies)
                 storage/ (models, repositories, migrations/)
                 jobs/ · service/ (app, routes/, errors, middleware, flags, readmodel) · evaluation/ · cli.py
  tests/ unit/ integration/ golden/ security/
web/     src/ app/ screens/ components/ importers/ api/ auth/ analytics/ i18n/ styles/ · e2e/
data/    samples/ seeds/ eval/ demo/ (synthetic, labeled)
docs/    design/ engineering-standards.md adr/ privacy/ runbooks/
.github/ workflows/ PULL_REQUEST_TEMPLATE.md CODEOWNERS
```

## 13. Foundations

| ID | Foundation | R1 / R2 | Contents |
|---|---|---|---|
| **F1** | Identity | R1 | Firebase Auth (Google Sign-In, PKCE) → server verifies the ID token → **Firebase session cookie** (`createSessionCookie`, ≤ 14 days, HttpOnly/Secure/SameSite=Lax) → revocation checked on sensitive operations. CSRF: `Origin` check + double-submit token on writes. Resource-based authorization in `identity/policies`. 13+ age statement at sign-up |
| **F2** | User data & controls | R1 | users, preferences, blocks, profile/Top 5, imported aggregates (consented), game sessions, badges, consents, audit log. ETags (AIP-154) and update masks (AIP-134). Delete (logical immediately, purge job ≤ 30 days) and export (JSON) |
| **F3** | Catalog | R1 partial / R2 | R1: ~100 seeds across genres and regions; labels; genres for every credited artist. R2: MusicBrainz JSON dumps (complete discographies, new releases) |
| **F4** | Audio descriptors | R2 | AcousticBrainz high/low-level data keyed by recording ID; artist medians; energy/mood scores (§16.5); coverage shown |
| **F5** | Social graph | R2 | mutual friendships, structured shares, inbox, block/report, rate limits, note screening, private by default |
| **F6** | Events & aggregation | R2 | consented minimal events; daily and weekly batch jobs; DP campus releases; listener counts for overlap |
| **F7** | Feed ranking | R2 | candidates → heuristic scoring → diversity (MMR) → explanations (§16.6) |
| **F8** | Import framework | R1 | Web Worker, ZIP (fflate), shape-based format detection (§15.5), size limits, progress, cancel; outputs aggregates only |

## 14. API

**Conventions (AIP):**
- resource names `artists/{artist}`, `recordings/{recording}`, `labels/{label}`, `users/{user}/…`;
- standard methods (Get, List, Create, Update with `updateMask`, Delete); custom methods `:verb`;
- `pageSize` (default 20, max 100) and opaque `pageToken`; `filter` per AIP-160 (a small subset); `orderBy`;
- ETags on mutable user resources;
- lowerCamelCase JSON;
- errors as `{"error": {"code", "status", "message", "details"}}` with canonical statuses (`INVALID_ARGUMENT`,
  `NOT_FOUND`, `PERMISSION_DENIED`, `UNAUTHENTICATED`, `ABORTED`, `RESOURCE_EXHAUSTED`, `FAILED_PRECONDITION`, `INTERNAL`).

**Process:** the OpenAPI contract is written first and passes an **API review** (end of week 2). The web lane builds
against a mock server (MSW) generated from it until the real endpoints land.

| Area | Methods | Tier |
|---|---|---|
| Catalog | GetArtist · ListArtistConnections · GetArtistConnection (evidence + sources) · ListArtistCollaborations · GetRecording (+ credits) · SearchCatalog · ListGenres · GetLabel | committed (GetLabel: target) |
| Analysis | FindPath · AnalyzePlaylist · CompareArtists (target) · CompareRecordings (R2) · ComputeUniverse (R2) | mixed |
| Play | GetDailyPuzzle · CheckMove · GetHint · RevealPuzzle (casual, stateless) · CreateGameSession / Move / Reveal · ListBadges (target) · CreateChallenge · ListFriendLeaderboard (R2) | mixed |
| User | GetUser · DeleteUser · ExportUserData (target) · GetPreferences / UpdatePreferences · List / Create / DeleteBlockedArtist · GetProfile / UpdateProfile (target) · GetPublicProfile (stretch) · ImportLibrary (target) | mixed |
| Social (R2) | CreateFriendRequest · AcceptFriendRequest · ListFriends · CreateShare · ListInbox · ReportShare | R2 |
| Feed (R2) | ListFeedItems · DismissFeedItem · GetCampusTrends | R2 |
| Ops | `/healthz` · `/v1/config` (feature flags) | committed |

**Limits:** search query ≤ 120 characters; path steps ≤ 6; alternatives ≤ 3; analyze/import payloads ≤ 2,000 artists
and ≤ 1 MB; per-client rate limits per method class. Exceeding a limit returns `INVALID_ARGUMENT` or `RESOURCE_EXHAUSTED`.

**Versioning:** `/v1` is additive only. Breaking changes need `/v2` and a deprecation window.

## 15. Data

### 15.1 Catalog model
- **Entities and facts:** artists, releases, recordings, labels, release labels, genres, artist genres, aliases, links,
  recording/release credits, artist relations, source mappings.
- **Raw records** carry provenance.
- **Rules:** deterministic UUIDv5 IDs; personal-life relations excluded.
- **Invariants:** v0's 18, plus non-empty normalized names, a closed role enum, consistent run statistics, and every
  label link backed by a raw record.

### 15.2 User data model

| Table | Fields | Notes |
|---|---|---|
| users | id, firebase_uid (unique), handle (unique, moderated), created_at, deleted_at | logical delete → purge |
| preferences | user_id, genres[], mood, energy_range, theme, etag | validated enums and ranges |
| blocked_artists | user_id, artist_id, created_at | PK (user, artist) |
| profiles | user_id, top_artist_ids (≤ 5), visibility, etag | private / link (stretch) / friends (R2) |
| imported_libraries | id, user_id, source_format, artist aggregates, created_at | consent required; no timestamps or track history |
| game_sessions, badges | … | server-authoritative |
| consents, audit_log | user_id, purpose/action, timestamps, request_id | – |
| R2 | friendships, shares, linked_accounts (KMS-encrypted tokens), events, campus_memberships, aggregates, feed_items | – |

### 15.3 Data classification and retention

| Class | Examples | Storage rule | Retention |
|---|---|---|---|
| Public | catalog, credits | normal | indefinite (versioned snapshots) |
| Account identifiers | uid, email (in Firebase only), handle | access-controlled; email not copied into our DB | until account deletion + 30 days |
| User preferences | blocks, genres, Top 5 | access-controlled | until deletion |
| **Sensitive personal** | listening aggregates (taste can reveal sensitive traits) | opt-in storage only; never logged; excluded from analytics | until the user deletes it or the account |
| Secrets | (R2) linked-account tokens | KMS-encrypted; Secret Manager for app secrets | until unlink |
| Operational | logs (no bodies), metrics | 30 days | 30 days |
| Backups | Cloud SQL automated backups | 7-day retention, so deletions finish within 30 days | 7 days |

### 15.4 Pipelines and reproducibility

`fetch` → immutable snapshot (content hash = version) → `ingest` (validation gate) → catalog DB + graph artifact
tagged with the snapshot version → read model. Every API response carries `graphVersion`. A rebuild from the same
snapshot is byte-for-byte identical (tested). Lineage is recorded in `ingestion_runs`.

### 15.5 Import formats

| Format | Detected by | Yields | Tier |
|---|---|---|---|
| Spotify `Playlist*.json` | `playlists[].items[].track` | playlists | committed |
| CSV/TSV with a header | header aliases (artist, "Artist Name(s)", …) | playlist or plays | committed |
| Spotify `StreamingHistory_music_*.json` | `{endTime, artistName, trackName, msPlayed}` | plays | target |
| Spotify `Streaming_History_Audio_*.json` | `master_metadata_album_artist_name` | plays (podcasts skipped) | target |
| Spotify `YourLibrary.json` | `tracks[]` | library | target |
| YouTube Music `watch-history.json` | `header == "YouTube Music"` | plays (artist from the "- Topic" channel) | target |
| ListenBrainz JSON/JSONL | `track_metadata` | plays + MusicBrainz artist IDs (exact) | target |
| ZIP | contains any of the above | recurse | committed |
| YouTube Music Takeout playlist CSV | `Video ID` column | server-side video lookup with a quota guard | stretch |
| M3U, TXT, manual column mapping | `#EXTINF` / lines / user mapping | playlist | stretch |

Limits: 100 MB per file, 500 MB per import. Unrecognized files are listed with a reason.

## 16. Algorithms and ranking

### 16.1 Graph categories and weights

| Kind | Weight | Category | Default |
|---|---|---|---|
| performed_with | 1.0 | Features & performances | on |
| produced_for / co_produced | 1.0 / 0.6 | Producers | on |
| contributed_to | 0.6 | Contributions | on |
| sampled | 0.4 | Samples | on |
| member_of / collaboration / supported / taught | 3.0 / 2.0 / 1.0 / 1.0 | Bands & projects | on |
| label_mates (same label, overlapping years) | 0.2 | Labels | off |
| engineered | 0.25 | Engineering | off |

Strength is the sum of an edge's evidence weights. These weights are a heuristic; calibrate them in R2 against
human pairwise judgments.

### 16.2 Algorithms

| Algorithm | Used by | Bound |
|---|---|---|
| Bidirectional BFS | FindPath (fewest), puzzle distance | ≤ 6 steps, ≤ 50k expansions |
| Dijkstra (cost = 1/strength) | FindPath (strongest) | ≤ 6 steps |
| Yen k-shortest | alternatives | k ≤ 3 |
| Single- and multi-source BFS | puzzle fairness, hints, playlist connectors, universe | ≤ 4 steps |
| PageRank, betweenness (sampled above 800 nodes, seeded) | connector tie-breaks | fixed iterations / pivots |

All of these support **node predicates** (genre, block, mood) so filters apply inside the search, not after it.

### 16.3 Daily puzzle
- **Pool:** well-known artists at distance 3–4 under the default categories.
- **Pick:** `hash(date) mod |pairs|`, with orientation from another hash bit. The same puzzle for everyone; #1 is the launch day.
- **Dates:** the client's local date, accepted by the server if launch ≤ date ≤ UTC today + 1.
- **Hints:** three options, at least one closer; deterministic.
- **Sharing:** the share card never names artists in between.

### 16.4 Playlist analysis
- **Cohesion** = share of artist pairs within 2 steps.
- **Connectors** = non-playlist artists linked to ≥ 2 playlist artists, scored by summed strength.
- **The thread** = concatenated shortest paths between consecutive playlist artists.

### 16.5 Mood and energy (R2)
- **Energy** ∈ [0,1] = the mean of: normalized BPM (clamped 60–180), normalized loudness, danceability, and
  (P(aggressive) − P(relaxed)) rescaled.
- **Mood** = argmax over {relaxed → chill, sad → melancholic, happy → happy, aggressive/party → hype} if the top
  probability ≥ 0.6; otherwise "mixed".
- Validate on ≥ 200 team-labeled tracks; changing either formula requires rerunning the evaluation.

### 16.6 Feed (R2)
- **Candidates:** new collaborations by connected artists; connectors; path of the day; explained suggestions;
  shares; campus cards.
- **Score** = affinity × freshness decay (half-life 7 days) × source weight. MMR diversity (≤ 2 items per artist per
  page). Blocks applied before ranking.
- **"Not interested"** suppresses that item and similar items for 30 days.
- **Offline evaluation:** time-split imported histories, recall@20 vs a popularity baseline.

## 17. Scale and capacity

**Reference deployment (R1):** roughly 5–15k artists after the M1-09 expansion (measure actuals). The whole graph fits
in memory per instance, and the read model rebuilds on deploy.

**At YouTube Music scale** (design only; illustrative figures, not YouTube Music data):

| Quantity | Formula | Example |
|---|---|---|
| Average API QPS | DAU × requests per user per day ÷ 86,400 | 10M × 5 ÷ 86,400 ≈ **580 QPS** |
| Peak QPS | average × peak factor | × 3 ≈ **1,700 QPS** |
| Adjacency memory | artists × average degree × bytes per entry | 2M × 20 × 12 B ≈ **480 MB** (+ evidence stored separately) |

**Design implications:**
- build the artist graph offline daily and shard it by artist ID;
- precompute each artist's top connections (the most common read);
- serve paths with bounded bidirectional search across shards;
- cache puzzle and playlist results by content hash;
- per-user state (blocks, preferences) is small and read-mostly.

## 18. Environments and operations

| Environment | What | How it's deployed |
|---|---|---|
| Local | `uv run`, `npm run dev`, PostgreSQL in Docker | developers |
| CI | ephemeral PostgreSQL service; full test suites | every PR |
| Staging | Cloud Run + small Cloud SQL + Firebase Hosting preview | auto-deploy on merge to `v2` |
| Demo (prod) | same, with a separate project or database | promote a tagged release manually |

**Release engineering:**
- build once, promote the same image;
- database migrations run as a job before traffic shifts, using **expand/contract** (never a breaking migration in
  the same release as the code that needs it);
- **rollback** = shift Cloud Run traffic to the previous revision (seconds) plus a feature-flag kill switch;
- flags are removed within 2 weeks of a full launch.

**Service level objectives (demo/staging):**
- availability ≥ 99.5% over 28 days (good = non-5xx);
- latency: 95% of requests within the §23 budget.

Alerts use multi-window burn rates (14.4× over 1 h, 6× over 6 h). Error-budget policy: when the budget is spent,
feature work pauses for reliability fixes.

**Monitoring:**
- an uptime check on `/healthz`;
- dashboards per surface (traffic, errors, latency);
- structured logs with trace IDs (Cloud Logging and Cloud Trace via OpenTelemetry).

**Runbooks** (`docs/runbooks/`): bad deploy, database unavailable, auth misconfiguration, quota exhausted (video
lookup), catalog build failure.

**Incidents:** a blameless postmortem for any outage longer than 30 minutes during demo weeks.

**Backups:** Cloud SQL automated daily backups (7 days) plus point-in-time recovery. The catalog can always be
rebuilt from snapshots.

**Cost** (estimate; confirm in the GCP pricing calculator):
- Cloud Run scales to zero at demo traffic;
- the smallest Cloud SQL instance is the main cost (roughly $10–30/month);
- Firebase Auth and Hosting stay within free tiers at our scale.

Set a **$25/month budget alert**.

## 19. Security

**Threat model (STRIDE):**

| Threat | Example | Controls |
|---|---|---|
| Spoofing | forged ID token or session | signature, audience, issuer and expiry checks; session revocation |
| Tampering | editing another user's data | resource authorization, ETags, server validation |
| Repudiation | disputed account change | audit log |
| Information disclosure | private profile via ID guessing (IDOR) | visibility checks, opaque IDs, tests |
| Denial of service | huge imports, deep path queries | payload limits, search bounds, rate limits, Cloud Run concurrency caps |
| Elevation of privilege | badges through API misuse | server-authoritative game sessions |

**Platform controls:**
- **Headers:** a strict Content-Security-Policy (no inline scripts, so the v0 inline theme script is replaced), HSTS,
  `X-Content-Type-Options`, `frame-ancestors 'none'`, `Referrer-Policy`.
- **Secrets and access:** Secret Manager for secrets; least-privilege service accounts; Cloud SQL via the connector
  with IAM authentication; no public database IP.
- **Supply chain:** CodeQL; Dependabot; secret scanning; GitHub Actions pinned by commit SHA; lockfiles enforced; a
  software bill of materials at launch.
- **Review:** a security review of identity in week 5 (§25.3); importer fuzzing nightly from week 6.

## 20. Privacy

### 20.1 Principles
- data minimization: aggregates, not history;
- consent for each optional use;
- user control: export and delete;
- no third-party analytics or ads SDKs;
- privacy review before every launch stage.

### 20.2 Privacy impact assessment (`docs/privacy/pia.md`, due week 3)
Covers: data inventory (§15.3), purposes, legal notices, the third parties used (Google Firebase/GCP; R2: Last.fm,
ListenBrainz, YouTube Data API), retention, user rights, and risks with mitigations. A **privacy notice and terms for
testers** must be live before any trusted-tester access.

### 20.3 Imports
Raw files are parsed on the device and never uploaded. AnalyzePlaylist and ImportLibrary receive names and counts only.
Saving to the account is a separate, explicit choice. Request bodies are never logged (tested).

### 20.4 Campus trends (R2): corrected privacy budget
- **Release cadence: weekly** (not daily), so the privacy budget doesn't grow 365 times a year.
- Each user contributes at most 10 artists per release (sensitivity bound).
- Laplace noise with ε = 1 per weekly release. Document the cumulative ε per user per term.
- Show only cohorts with ≥ 25 opted-in users. Never show or export data for an individual.
- Final parameters are set in the privacy review and published in `docs/privacy/`.

## 21. Testing

| Type | Scope | When | Gate |
|---|---|---|---|
| Unit + property | core algorithms (vs networkx), filters, game rules, parsers, scoring | every PR | all pass; core ≥ 90% line coverage |
| Integration | ingest → quality → projection; repositories; migrations up and down | every PR (PostgreSQL) | all pass |
| Contract | API vs OpenAPI; generated TS types compile | every PR | no drift |
| Security | authorization matrix, IDOR, CSRF, session fixation, tampered tokens, badge abuse | every PR | all pass |
| Golden data | snapshot facts, collaborations audit, known paths | every PR | exact |
| Evaluation gates | search MRR ≥ 0.95; import-match precision ≥ 0.98; puzzle fairness 100% | every PR | thresholds |
| E2E + accessibility | Playwright per screen at 390 px and 1440 px; axe | PR (smoke) + nightly (full) | zero serious/critical axe issues |
| Fuzzing | importers with malformed and huge files | nightly from week 6 | no crashes or hangs |
| Load | k6 scenarios per endpoint class | weekly from week 6; final in M8 | §23 budgets |
| Manual | screen reader pass; exploratory testing per release | each release | issues filed |

**Test data rule:** fixtures use fictional names. Real names appear only in the MusicBrainz snapshot and labeled sets.
Flaky tests are quarantined within 24 h with an owner.

## 22. Metrics and experiments

**Analytics schema:** defined in `web/src/analytics/events.ts`, reviewed like an API. Events are aggregate counters
with no user IDs, no free text and no listening data.

| Event | Properties |
|---|---|
| `explore_expand`, `evidence_open`, `source_open` | surface |
| `path_found`, `path_not_found`, `path_shared` | mode, steps |
| `compare_done` | type |
| `puzzle_start`, `puzzle_move`, `puzzle_complete`, `puzzle_share` | result, steps vs par, hints |
| `import_start`, `import_complete`, `import_fail` | format, size bucket, match-rate bucket |
| `block_add`, `block_remove`, `top5_set` | – |

**Experiments:** classmate-scale traffic can't power A/B tests. For example, detecting +2 points on a 30% completion
rate (α = 0.05, power 0.8) needs ≈ 8,400 users per arm. So R1 decisions rely on usability research (§11) and dogfood
metrics. The flag system logs exposure, so a YouTube Music team could run real experiments with the same switches.

**Launch metrics per surface:**

| Surface | Primary metric | Guardrail |
|---|---|---|
| Explore / Six Degrees | sessions with ≥ 1 expansion or path | p95 latency, error rate |
| Play | completion rate; next-day return | give-up rate |
| Import | success rate by format | parse failures |
| Blocks | usage rate | blocked-artist leaks (must be 0) |

## 23. Performance budgets

These are proposals until first measured. Record actuals; don't edit targets afterwards.

| Budget | Target |
|---|---|
| p95 GetArtist / connections / collaborations / recording | ≤ 100 ms |
| p95 SearchCatalog | ≤ 50 ms |
| p95 FindPath, CheckMove, CompareArtists | ≤ 150 ms |
| p95 AnalyzePlaylist (2,000 artists) | ≤ 1.5 s |
| Connection web | ≥ 55 fps pan/zoom at 300 nodes on a reference laptop |
| Web initial JS (gzip) | ≤ 200 KB; the Firebase Auth SDK lazy-loaded on sign-in |
| Largest Contentful Paint, mid-tier mobile (Lighthouse, 4G) | ≤ 2.5 s |
| 100 MB import | ≤ 15 s in a worker; main-thread long tasks ≤ 50 ms |

## 24. Dependencies and licenses (planned)

| Package | Use | License | Note |
|---|---|---|---|
| FastAPI, Pydantic, SQLAlchemy, Alembic | service, models, migrations | MIT | – |
| uvicorn, httpx | server, HTTP client | BSD-3 | – |
| psycopg 3 | PostgreSQL driver | **LGPL-3.0** | unmodified dynamic use; legal confirm |
| firebase-admin, google-auth | token verification, sessions | Apache-2.0 | – |
| React, Vite, Vitest, react-router, TanStack Query | web | MIT | – |
| Firebase JS SDK | sign-in | Apache-2.0 | lazy-loaded |
| d3-force | layout | ISC | – |
| fflate, papaparse | ZIP, CSV | MIT | – |
| Playwright, gts | E2E, lint | Apache-2.0 | dev only |
| @axe-core/playwright | accessibility tests | **MPL-2.0** | dev only |
| hypothesis | property tests | **MPL-2.0** | dev only |
| networkx | test oracle | BSD-3 | dev only |

**Policy:** permissive licenses for anything shipped; flagged licenses need a legal check before launch; every new
dependency is justified in its PR.

---

# Part C: Execution

## 25. Team and governance

### 25.1 Roles
Assign names in the kickoff. One person can hold several roles.

| Role | Responsibilities |
|---|---|
| Tech lead (TL) | architecture, API review, technical decisions, critical path |
| Product manager (PM) | scope, priorities, tiers, sponsor contact, launch decisions |
| UX lead | mocks, content design, research rounds, accessibility review |
| Lane A lead: data and core | M1, M2, game core, evaluation sets |
| Lane B lead: service and identity | M3, M4, operations |
| Lane C lead: web | M5, Play UI, E2E |
| Lane D lead: import | M6, fuzzing |
| Privacy and security champion | PIA, threat model, reviews (rotate if needed) |

### 25.2 Decision rights (RACI)

| Decision | Responsible | Accountable | Consulted | Informed |
|---|---|---|---|---|
| Scope and tiers | PM | PM | TL, UX, sponsor | team |
| Architecture and APIs | TL | TL | lane leads | team |
| UX and content | UX | PM | TL | team |
| Privacy and security | champion | TL | sponsor/instructor | team |
| Launch stage changes | PM | PM | TL, champion, UX | sponsor |

Decisions are recorded as ADRs in `docs/adr/`.

### 25.3 Review calendar

| Week | Date | Review | Gate for |
|---|---|---|---|
| 1 | Fri Oct 9 | Design review (design doc + this plan) | starting M1 |
| 2 | Fri Oct 16 | API review (OpenAPI contract); UX review of mocks | M3, M5 |
| 3 | Fri Oct 23 | Privacy design review (PIA draft) | M4, M6 |
| 5 | Fri Nov 6 | Security review (identity) | trusted testers |
| 7 | Fri Nov 20 | Dogfood go/no-go | UX-02 |
| 8 | Tue Dec 1 | Launch review (privacy, security, accessibility, legal, SLOs, metrics) | demo |

### 25.4 Rituals
- weekly 30-minute plan and burn-down review;
- Friday demo of what merged;
- PR review within 24 hours;
- an issue triage rotation.

### 25.5 Definitions
- **Definition of ready (issue):** change ID, acceptance criteria, linked design/API, estimate ≤ 2 pd (otherwise
  split), dependencies resolved, test approach noted.
- **Definition of done (change):** `engineering-standards.md` §7, plus flag-gated if user-visible, analytics events
  added if specified, docs and runbooks updated.

## 26. Release plan and capacity

### 26.1 Capacity (replace the assumptions with real numbers, D18)

| Input | Assumption |
|---|---|
| People | 4 |
| Weeks to the demo | 9 |
| Focused dev days per person per week | 2 |
| **Capacity** | **72 pd** |

### 26.2 Tiers

| Tier | Meaning | Contents | Effort |
|---|---|---|---|
| **R1 committed** | the demo fails without it; planned within capacity | foundations M0–M3, F1/F2 core, US-18, US-17, US-03, US-02/06 (no labels), US-16, US-10 (Spotify playlists + CSV), US-12, US-04 casual puzzle, hardening, research, demo | **≈ 66 pd** |
| **R1 target** | planned next; drops first if behind | US-09 Top 5, US-05 compare, S5 song page, US-08 history imports, badges + streaks + game sessions, label toggle, data export, licenses/SBOM | **≈ 14.5 pd** |
| **R1 stretch** | only if ahead | shareable profile link, anonymous merge, Takeout playlist lookup, M3U/TXT/mapping UI | **≈ 3.5 pd** |
| **R2** | continuation / handoff | §27 M10–M16 | **≈ 70 pd** |

**Buffer:** committed 66 pd against 72 pd capacity is an **8% buffer**, below the ~15–20% that keeps a schedule
honest. Before week 2, either confirm higher capacity (≥ 2.3 days per person per week gives ≈ 83 pd) or move
US-12 genre selection and the canvas renderer (use SVG with a 150-node cap) to target (−3 pd → 13% buffer).

**R1 demo story (≈ 5 min):** sign in → import a Spotify playlist → see its hidden connectors → open an artist's
collaborations → find six degrees to a surprising artist → filter by genre → block an artist and watch them disappear
→ play the daily puzzle. Target additions: compare two artists; pin your Top 5; earn a badge.

## 27. Milestones and changes

Tier: **C** committed · **T** target · **S** stretch. Estimates in ideal person-days.

**M0 Repo and process foundations (week 1)**: C 3.35
| ID | Change | Tier | Est |
|---|---|---|---|
| M0-01 | Commit step 1 (clean slate, design doc, standards) | C | 0.1 |
| M0-02 | Record decisions D1–D18 as ADRs | C | 0.5 |
| M0-03 | GitHub governance: protection, templates, CODEOWNERS, labels, one issue per change ID | C | 0.5 |
| M0-04 | Supply chain: CodeQL, Dependabot, secret scanning, Actions pinned by SHA | C | 0.25 |
| M0-05 | Tooling skeleton `server/` + `web/` + CI | C | 1.5 |
| M0-06 | Feature-flag registry + `/v1/config` + web hook | C | 0.5 |

**M1 Catalog foundation (weeks 2–3)**: C 8.0
| ID | Change | Tier | Est |
|---|---|---|---|
| M1-01 | `core/text`: Unicode-aware normalization (fixes v0's erasure of non-Latin names) | C | 1 |
| M1-02 | `core/ids`, `core/model` (+ labels, genres) | C | 0.5 |
| M1-03 | MusicBrainz snapshot I/O, parsers, client (port) | C | 1 |
| M1-04 | Canonicalization (port) + label info | C | 1 |
| M1-05 | Storage models + Alembic (up/down tested) | C | 1 |
| M1-06 | Ingest: source-scoped sync, run records (port) | C | 1 |
| M1-07 | Quality invariants + validation gate + CLI | C | 0.5 |
| M1-08 | Golden snapshot test + reproducibility test | C | 0.5 |
| M1-09 | Catalog expansion: ~100 seeds, labels, genres for all credited artists; license check (§4) | C | 1.5 |

**M2 Core library (week 3)**: C 6.0 · T 1.0
| ID | Change | Tier | Est |
|---|---|---|---|
| M2-01 | Algorithms + node predicates (port + extend) | C | 1.5 |
| M2-02 | Projection from fact iterators; categories incl. label mates | C | 1 |
| M2-03 | Explanations via message IDs | C | 0.5 |
| M2-04 | Resolution matcher + batch API | C | 0.5 |
| M2-05 | Search (Unicode fix, artist-over-album tie-break) + MRR gate | C | 1 |
| M2-06 | `core/collaborations` | C | 1 |
| M2-07 | `core/filters` (genre, block) | C | 0.5 |
| M2-08 | `core/compare` (artists) | T | 1 |

**M3 Service API v1 (weeks 2–4)**: C 8.0 · T 0.5
| ID | Change | Tier | Est |
|---|---|---|---|
| M3-01 | OpenAPI contract + API review + MSW mock server for the web | C | 1 |
| M3-02 | Skeleton: error model, request IDs, logging, `/healthz`, metrics, flags, security headers | C | 1 |
| M3-03 | Read model (atomic reload, `graphVersion`) | C | 0.5 |
| M3-04 | Artists, connections, connection evidence + sources | C | 1.5 |
| M3-05 | Recordings, search, genres | C | 1 |
| M3-06 | FindPath (filters) + collaborations | C | 1 |
| M3-07 | Generated TS types; rate and payload limits | C | 0.5 |
| M3-08 | Deployable: container, staging (Cloud Run + Cloud SQL), continuous deploy, migration job, budget alert | C | 1.5 |
| M3-09 | CompareArtists endpoint | T | 0.5 |

**M4 Identity and user data (weeks 4–6)**: C 7.5 · T 2.0 · S 1.0
| ID | Change | Tier | Est |
|---|---|---|---|
| M4-01 | Firebase Auth (web) + token verification + session cookies + CSRF | C | 2 |
| M4-02 | Users, preferences (validation, ETags, update masks), audit log | C | 1.5 |
| M4-03 | Blocked artists + enforcement sweep (AC-17.1) | C | 1.5 |
| M4-04 | Delete account + purge job | C | 1 |
| M4-05 | Security test suite (§21) | C | 1.5 |
| M4-06 | Profile + Top 5 (private) | T | 1.5 |
| M4-07 | Export my data | T | 0.5 |
| M4-08 | Shareable profile link + handle moderation | S | 0.5 |
| M4-09 | Anonymous → signed-in merge | S | 0.5 |

**M5 Exploration surfaces (weeks 3–7)**: C 13.5 · T 4.0
| ID | Change | Tier | Est |
|---|---|---|---|
| M5-01 | Web shell: routes, navigation, Material 3 tokens, i18n, auth UI, flags, "About our data" and privacy pages | C | 3 |
| M5-02 | Search (accessible combobox) | C | 1 |
| M5-03 | Artist page + Collaborations tabs (US-16) | C | 2 |
| M5-04 | Explore: canvas connection web + list view + toggles (US-02/06) | C | 3 |
| M5-05 | Six Degrees + share link (US-03) | C | 2 |
| M5-06 | Genre filter component (US-12) | C | 1.5 |
| M5-07 | E2E + axe for committed screens | C | 1 |
| M5-08 | Song page (credits) | T | 1 |
| M5-09 | Compare screen (US-05) | T | 2 |
| M5-10 | Labels toggle + label nodes | T | 1 |

**M6 Import (weeks 3–7)**: C 6.0 · T 3.5 · S 2.5
| ID | Change | Tier | Est |
|---|---|---|---|
| M6-01 | Worker framework, ZIP, limits, progress, cancel | C | 1.5 |
| M6-02 | Spotify playlists + CSV with header detection | C | 1.5 |
| M6-03 | Privacy screen + aggregation | C | 0.5 |
| M6-04 | AnalyzePlaylist + playlist screen (US-10) | C | 1.5 |
| M6-05 | Labeled import-match set (≥ 200 names, incl. ambiguous and non-Latin) + precision gate | C | 1 |
| M6-06 | Spotify history and library → "Your artists" + Top 5 suggestions (US-08) | T | 2 |
| M6-07 | YouTube Music Takeout history + ListenBrainz | T | 1.5 |
| M6-08 | CSV manual mapping, M3U, TXT | S | 1.5 |
| M6-09 | Takeout playlist CSV via video lookup (quota guard) | S | 1 |

**M7 Play (weeks 5–7)**: C 3.5 · T 3.0
| ID | Change | Tier | Est |
|---|---|---|---|
| M7-01 | `core/game` (port) | C | 1 |
| M7-02 | Puzzle API (casual, stateless) | C | 1 |
| M7-03 | Play screen, share card, local progress | C | 1.5 |
| M7-04 | Server game sessions + badges + streaks (**after M4-01**) | T | 3 |

**M8 Hardening and launch readiness (week 8)**: C 5.0 · T 0.5
| ID | Change | Tier | Est |
|---|---|---|---|
| M8-01 | Load test vs budgets; fix hot spots | C | 1 |
| M8-02 | Accessibility audit (axe + NVDA + VoiceOver) | C | 1 |
| M8-03 | Pseudo-localization + RTL | C | 0.5 |
| M8-04 | Privacy and security reviews; fuzzing findings | C | 1 |
| M8-05 | Observability: SLO dashboards, burn-rate alerts, runbooks | C | 1 |
| M8-06 | Launch review | C | 0.5 |
| M8-07 | Dependency and license audit + SBOM | T | 0.5 |

**UX research (cross-cutting)**: C 2.0. UX-01 (week 3) 1 pd · UX-02 (week 7) 1 pd.

**M9 Demo and handoff (week 9)**: C 3.1
| ID | Change | Tier | Est |
|---|---|---|---|
| M9-01 | Promote the release to demo (or record a video) | C | 0.5 |
| M9-02 | Demo script + two rehearsals | C | 0.5 |
| M9-03 | Handoff package (design doc, API spec, core docs, evaluations, limitations, integration guide) | C | 1.5 |
| M9-04 | Record final measurements (evaluations, load test, SUS) | C | 0.5 |
| M9-05 | Replace `main` with `v2`; delete this plan | C | 0.1 |

**Totals:** C ≈ 66 · T ≈ 14.5 · S ≈ 3.5.

**R2 (≈ 70 pd)**

| Milestone | Contents | Est |
|---|---|---|
| M10 Social | F5; US-13; US-09 common ground; safety | 12 |
| M11 Competitive play | US-04 friend leaderboards, challenges | 4 |
| M12 Platform sync | US-08 Last.fm/ListenBrainz sync; encrypted tokens; unlink/delete; Spotify after legal review | 6 |
| M13 Audio | F4; US-14, US-15, US-01; labeled validation | 15 |
| M14 Events and For You | F6, F7, US-07; offline evaluation | 17 |
| M15 Campus and listener overlap | US-11 (verification, DP), US-05 overlap | 8 |
| M16 Full catalog | F3 R2 dumps; complete discographies; new releases | 8 |

## 28. Schedule (R1)

| Week | Dates | A: data and core | B: service and identity | C: web | D: import | PM / UX |
|---|---|---|---|---|---|---|
| 1 | Oct 7–13 | M0-05 | M0-03, M0-04, M0-06 | M0-05 web | format research | M0-02, PIA start, mocks start |
| 2 | Oct 14–20 | M1-01…04 | M1-05…06, M3-01 contract | shell against mocks (M5-01) | fixtures, M6-01 | mocks + UX review |
| 3 | Oct 21–27 | M1-07…09 (fetch in background), M2-01…03 | M3-02…04 | M5-01, M5-02 | M6-01, M6-02 | UX-01, privacy review |
| 4 | Oct 28–Nov 3 | M2-04…07 | M3-05…08 | M5-03 | M6-03, M6-04 | – |
| 5 | Nov 4–10 | M7-01, M6-05 | M4-01…02 | M5-04 | M6-06 (T) | security review |
| 6 | Nov 11–17 | M7-02, M2-08 (T) | M4-03…05 | M5-05, M5-06 | M6-07 (T), fuzzing | – |
| 7 | Nov 18–24 | M7-04 (T, needs M4-01) | M4-06…07 (T) | M7-03, M5-07, M5-08…10 (T) | M6-08…09 (S) | UX-02, dogfood go/no-go |
| 8 | Nov 25–Dec 1 | M8 | M8 | M8 | M8 | launch review |
| 9 | Dec 2–8 | M9 | M9 | M9 | M9 | demo |

**Critical path:** M0-05 → M1 → M2 → M3-04 → M5-03/04/05 → M5-07 → M8. Identity (M4-01) is the riskiest new piece;
spike it in week 2. The web lane is unblocked from week 2 by the OpenAPI contract and mock server.

**If the team is smaller:** with 3 people, keep committed only (move US-12 to target). With 2, committed minus
US-12, M5-10, M6-02 CSV; expect M8 in week 9.

## 29. Traceability

| Story | Surface | Acceptance criteria | Changes | Tests | Metric |
|---|---|---|---|---|---|
| US-18 Login | S9 | AC-18.1–4 | M4-01, 02, 04, 05 | security suite, E2E sign-in, deletion test | sign-in success rate |
| US-17 Block | S9 + all | AC-17.1–3 | M2-07, M4-03, M4-09 | enforcement sweep, property tests | blocked-artist leaks = 0 |
| US-03 Six degrees | S2 | AC-3.1–4 | M2-01, M3-06, M5-05 | golden paths, filter property tests, E2E | path_found / path_shared |
| US-02/06 Graph / web | S1 | AC-2.1–3 | M2-02, M3-04, M5-04, M5-10 | E2E, fps test, axe | explore_expand |
| US-16 Collaborations | S4 | AC-16.1–2 | M2-06, M3-06, M5-03 | golden audit, E2E | evidence_open |
| US-10 Upload playlist | S8 | AC-10.1–3 | M6-01…05, M6-08…09 | parser fixtures, precision gate, E2E request check | import success by format |
| US-12 Genre | S1, S2 | AC-12.1–2 | M1-09, M2-07, M5-06 | property tests | filter usage |
| US-04 Gamification | S6 | AC-4.1–4 | M7-01…04 | fairness test, badge abuse test, time-zone tests | completion, return |
| US-09 Top 5 | S9 | AC-9.1–2 | M4-06, M4-08 | authorization matrix | top5_set |
| US-05 Artist comparison | S3 | AC-5.1–2 | M2-08, M3-09, M5-09 | golden comparisons | compare_done |
| US-08 Platform connection | S8 | AC-8.1–3 | M6-06, M6-07, M12 | fixtures, performance test, unlink test | import success |
| US-01 Song comparison | S3 | §7 R2 table | M13 | golden pairs, coverage | – |
| US-07 For You | S7 | §7 R2 table | M14 | offline evaluation, block test | card tap-through |
| US-11 Campus | S7 | §7 R2 table | M15 | DP tests, threshold test | – |
| US-13 Friends | S9 | §7 R2 table | M10 | abuse tests | shares sent |
| US-14/15 Mood / Energy | S1, S7 | §7 R2 table | M13 | labeled agreement | filter usage |

## 30. Risks

| Risk | L | I | Trigger | Mitigation | Owner |
|---|---|---|---|---|---|
| Committed scope exceeds capacity | High | High | burn-down behind by > 3 pd at any weekly review | drop target items first; §32 cut order | PM |
| Identity or security defect | Medium | High | any failing security test or review finding | Firebase Auth (no custom crypto); week-5 review | TL |
| Spotify terms block sync | High | Medium | legal review outcome | exports, Last.fm/ListenBrainz | PM |
| Non-commercial genre license | Medium | Medium | license check in M1-09 | isolate behind the adapter; document | Lane A |
| Common-name mismatches in imports | High | High | precision < 0.98 on the labeled set | precision-first matching; ambiguity shown | Lane A |
| Usability failure on core flows | Medium | High | UX-02 task success < 80% | fix P0 issues before launch review | UX |
| Web blocked on API | Medium | Medium | contract late in week 2 | contract-first + mocks | TL |
| Graph performance | Medium | Medium | fps < 55 at 300 nodes | canvas, node caps, SVG fallback with a lower cap | Lane C |
| GCP project or billing unavailable | Medium | Medium | no project by week 3 | local demo + recorded video | PM |
| IRB or consent requirement discovered late | Low | Medium | instructor's answer | ask in week 1 | UX |
| YouTube trademark confusion | Medium | Medium | design review | "styled after"; no YouTube assets | UX |
| Team availability (exams, Thanksgiving) | High | Medium | week-8 load | buffer; P2 first to cut | PM |
| Social abuse (R2) | Medium | High | before any social launch | safety controls first | champion |
| Campus re-identification (R2) | Medium | High | before any campus launch | DP, cohort minimum, review | champion |

## 31. What we reuse from v0

| v0 path | v2 destination | Action |
|---|---|---|
| `core/text.py` | `core/text.py` | Port + **fix**: normalization erased all non-Latin characters ("방탄소년단" → "") |
| `core/ids.py`, `resolution/matcher.py` | `core/` | Port; add batch resolution |
| `integrations/musicbrainz/*`, `pipelines/*` | `catalog/` | Port; Alembic; labels; settings-based paths |
| `graph/algorithms.py`, `graph/projection.py` | `core/graph/` | Port; node predicates; build from fact iterators |
| `search/index.py` | `core/search/` | Port + Unicode fix + artist-over-album tie-break |
| `services/explain.py` | `core/explain/` | Port; message IDs |
| `services/game_service.py`, `frontend/src/state/game.ts` | `core/game/`, `web/src/screens/play/` | Port; server sessions for ranked play |
| `readmodel.py` | `service/readmodel.py` | Port; avoid duplicate concurrent cache computation |
| `api/*`, `schemas/*`, `services/*_service.py`, `repositories/` | `service/`, `storage/` | **Rewrite** to AIP style |
| `agent/*` and agent evaluation | – | **Delete** (D3) |
| `frontend/` | `web/` | Rewrite; port the accessible search pattern, the validated palette, the game logic; replace the inline theme script (CSP) |

## 32. Scope control

**Never cut:**
- tests for shipped code;
- privacy guarantees;
- evidence on every connection;
- identity security;
- accessibility basics;
- the launch review.

**Cut order if behind** (top first):
1. Stretch items (M4-08, M4-09, M6-08, M6-09)
2. M8-07 SBOM
3. M5-10 labels toggle
4. M7-04 badges, streaks and sessions (keep the casual puzzle)
5. M6-06/07 history imports (keep playlists)
6. M5-09 / M2-08 / M3-09 Compare
7. M4-06/07 Top 5 and export
8. US-12 genre selection (M5-06; keep the data)

## 33. Analysis questions

1. **Capacity:** what are our real numbers (§26.1)? Do we accept an 8% buffer, or trim committed now?
2. **Sponsor (D1):** what exactly do we ask Google for, and by when?
3. **Legal:** who checks Spotify's terms, MusicBrainz's genre license, psycopg's LGPL license and the IRB question,
   and by which date?
4. **Personas (§2):** do they match who we actually want to serve? Which persona does the demo story serve best?
5. **R2 (social, campus, For You):** keep them for a next team, or hand them to YouTube Music as designs only?
6. **Ownership:** who takes each role (§25.1) and each lane?
7. **Coverage:** does each of the 18 stories read the way the team meant it (§7)? Note any misreadings.

---

## Appendix: glossary

| Term | Meaning |
|---|---|
| AIP | Google's API Improvement Proposals (google.aip.dev) |
| CUJ | Critical user journey |
| DP | Differential privacy: calibrated noise so no individual's data can be inferred |
| ETag | Version tag on a resource, used to reject stale updates |
| Evidence | A stored, sourced fact (credit or relationship) that justifies a connection |
| MMR | Maximal marginal relevance: a diversity re-ranking method |
| pd | Ideal person-day of focused engineering, including tests |
| PIA | Privacy impact assessment |
| SLO | Service level objective; the error budget is the allowed shortfall |
| SUS | System Usability Scale (0–100) |
| Tier C / T / S | committed / target / stretch within R1 |
