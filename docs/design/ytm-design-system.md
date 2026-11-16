# SongNexus design system (YouTube Music idiom)

How the web app looks and why, so new screens match the ones already built.
Read this before touching anything under `web/src/styles` or adding a screen.

## Principles

1. **It should read as part of YouTube Music.** Near-black page, white ink, grey
   secondary text, pill buttons, square-ish chips, shelves of cover cards, a
   guide down the side. Red is for the brand mark and "new" signals only.
2. **The short answer is on the page; the full answer is one tap away.** A list
   row says "40 credits · Producers"; selecting it shows every credit with its
   source. Use `<details class="more">` for explanations, a panel or sheet for
   evidence. Never put the long version first.
3. **Every claim is backed.** A connection is a set of credits, each with a
   source link. If something isn't in the data, say "not in our data yet".
4. **The same artist looks the same everywhere.** Covers are generated from the
   name (`hueOf`), and the list avatar, the shelf card, the page hero and the
   node in the connection web all use that one cover.

## Structure

| Destination | Route | What it holds |
| --- | --- | --- |
| Home | `/` | Shortcut chips, one feature, shelves (recent, top artists, starting points), quick picks |
| Explore | `/explore` | Start a connection web; links to path, compare artists, compare songs |
| Connection web | `/explore/:id` | Full-bleed canvas with a details panel |
| Find a path | `/six-degrees` | Under Explore in the guide |
| Compare | `/compare`, `/compare/songs` | Under Explore in the guide |
| Play | `/play` | Daily puzzle |
| Friends | `/friends` | Invites, inbox, shares |
| Library | `/library` | Imports, connected services, listening |
| You | `/you` | Reached from the avatar |

Retired in the redesign, with redirects in `App.tsx` (`RETIRED`): Discover
(merged into Explore), Games (one game: goes straight to Play), Your music (was
three links: goes to Library), Ask (a keyword router presented as an
assistant), Reels and Around you (no data behind them). Bring the last three
back only with real data or a real model behind them.

## Files

| File | Holds |
| --- | --- |
| `styles/tokens.css` | Color roles, type scale, shape, spacing, motion |
| `styles/base.css` | Element defaults, focus, native inputs |
| `styles/primitives.css` | Buttons, chips, cards, page header, `.more`, shelves, covers |
| `styles/shell.css` | Top bar, guide (full, rail, phone tab bar), page padding |
| `styles/components.css` | Lists, tabs, fields, sheets, friends, timeline, meters |
| `styles/home.css` | Home feature, quick picks, Explore hub |
| `styles/web.css` | The connection web page and the evidence block |

## Tokens you will use most

- Surfaces: `--md-surface` (page), `--md-surface-container-low` (cards),
  `--md-surface-container-high` (floating controls, menus).
- Text: `--md-on-surface`, `--md-on-surface-variant` (secondary, 8.6:1 on the page).
- Fills for chips, hover and pressed: `--fill-1`, `--fill-2`, `--fill-3`.
- Hairlines: `--md-outline-variant`.
- Brand: `--brand` (decoration), `--brand-strong` with `--on-brand` (badges with text).
- Data lines: `--series-1..3`, `--neutral-strong`, `--neutral-soft` through
  `components/encoding.ts`. Do not pick other colors for data.
- Page padding: `--page-x`, `--page-y` (set on `.main`; use them to bleed a hero).

Dark is the default. Light exists (`data-theme="light"`) and every role is
`light-dark(light, dark)`, so check both when adding a color.

## Components

- **Buttons**: `.btn` plus `--filled` (one primary action per group), `--tonal`,
  `--outlined`, `--text`, `--danger`; `--compact` for dense bars. Icons go
  before the label.
- **Chips**: `.chip` with `aria-pressed`, `aria-checked` or `aria-current`.
  `.chips--scroll` for a single scrolling row.
- **Page header**: `.page-header` with `.strapline`, `h1`, `.lead`. Entity pages
  (artist, song) use `.artist-hero` with a `Cover`.
- **Shelf**: `Shelf` and `CoverCard` (`round` for artists).
- **Quick picks**: `ToolGrid` with entries from `components/Tools.tsx`. Add a
  new feature there once and it appears wherever tools are listed.
- **Lists**: `.list` and `.list-row`; `Avatar` for the leading cover.
- **Evidence**: `ConnectionEvidence` (inline, for panels) or `ConnectionSheet`
  (bottom sheet). Both show the count and kinds first, then credits.
- **Icons**: `Icon` with a `name` from `components/Icon.tsx`; `size` when not 24.

## The connection web

`explore/ConnectionWeb.tsx` draws; `screens/ExploreScreen.tsx` owns the state
and the page; `explore/graphState.ts` is the pure reducer (unit-tested).

- An artist is a circle carrying their cover; the starting artist has a red
  ring, an opened artist a grey ring, the selected one a white ring.
- A line is a connection: color and dash give the kind, width the strength.
- Pointing at something lights its neighborhood and dims the rest; a tooltip
  names it. Click selects; double-click opens an artist's connections; drag
  moves an artist; scroll or pinch zooms.
- The camera frames the web when it settles and after each expansion, until the
  listener pans, zooms or drags. "Fit to screen" hands it back.
- Names are placed by importance and skipped when they would overlap.
- The panel shows the starting artist by default, an artist when one is
  selected, and the credits when a line is selected.
- Filters: kinds of connection, a minimum number of credits (client-side), and
  genres. A red dot on the filter button means filters are narrowing the web.
- The list view is the accessible equivalent and must keep carrying the same
  content. Keep these accessible names stable, the end-to-end tests use them:
  "Undo", "Expand the 5 strongest", "List", the trail navigation "Artists you
  expanded", and the canvas label "Connection web of {name}…".

## Rules that are easy to break

- Every user-visible string goes through `t()` and lives in `i18n/messages.ts`.
  The pseudo-locale test fails on a hard-coded string.
- Logical properties only (`inline`/`block`), so right-to-left works. The one
  exception is an element positioned with a pixel transform (the web tooltip).
- Interactive targets are 44px, or a smaller visual with a `::after` hit area.
- No inline `<style>` and no third-party font or script requests (CSP). Fonts
  are self-hosted through `@fontsource-variable/roboto`.
- Initial JavaScript stays under 200 KB gzip (`scripts/check-bundle-size.mjs`).
