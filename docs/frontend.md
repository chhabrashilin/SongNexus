# Part 7: Frontend architecture

React 19 + TypeScript (strict, `noUncheckedIndexedAccess`) + Vite; D3 modules (`d3-force`, `d3-zoom`,
`d3-drag`, `d3-selection`) for the graph only. No UI framework and no global state library: the app has one
graph model and a handful of panels, which `useReducer` handles cleanly.

## Layout

```
┌ topbar: brand · universal search (artists, songs) · Explore | Connect | Ask ───────────────────────┐
├ left: mode panel ─────────┬ stage: force-directed graph ──────────────┬ right: details ──────────────┤
│ Explore: filters, legend  │ zoom/pan · drag · hover · click · dbl-click│ Artist / Connection / Track   │
│ Connect: from, to, mode   │ path highlight (others dimmed) · Fit       │ evidence · sources            │
│ Ask: question, answer,    │ "Clear highlighted path"                   │ "Where does this come from?"  │
│      trace, limitations   │                                            │                               │
└ footer: dataset size · license · graph version ────────────────────────────────────────────────────┘
```

Below 1000 px the columns stack (graph first, 60 vh). A 390 px phone width was checked in a headless-browser run.

## Source structure

```
src/
  App.tsx                 composition: state, data loading, layout
  graph/GraphCanvas.tsx   D3 force layout; React owns data, D3 owns the SVG
  state/graphState.ts     pure reducer: reset, merge (progressive expansion), select, showPath (+ tests)
  components/             SearchBox, FilterBar, DetailPanels (Artist/Edge/Track), ConnectPanel, AskPanel,
                          PathView, Provenance
  services/api.ts         typed client; error envelope → ApiError (+ tests)
  hooks/useApi.ts         keyed fetching with cancellation (a stale response never overwrites a newer one)
  types/api.ts            mirrors backend DTOs
  utils/format.ts         colors, labels, helpers
```

## Visual design and encoding

Dark theme by default, light theme via the top-bar toggle (stored per browser; the page works without storage).
Design tokens live on `:root` / `:root[data-theme="light"]` in `styles.css`.

Connection types are encoded by **line color and dash together**. Any two types can meet in the graph, so the
palette has to separate *all* pairs. Only three categorical hues pass that check in both themes (validated
with the dataviz palette validator: worst colorblind-simulated ΔE 9.2 light / 9.4 dark; normal-vision ΔE ≥ 20.9).
Those three go to the most common types (performed together, production, contributions). Bands, samples and
engineering are neutral lines told apart by solid, dashed and dotted strokes. The violet accent is reserved for UI chrome
and the highlighted path, never for data. The legend, the evidence sentences and the artist panel repeat every
type in text, so identity never depends on color alone (this matters in light mode, where two series colors sit just below
3:1 contrast against the background).

## Graph interaction model

| Action | Result |
|---|---|
| Search → pick artist | graph **resets** to that artist's neighborhood (limit from the slider) |
| Click node | select → right panel shows artist details |
| Double-click node / "Expand" | **merge** that artist's top 15 neighbors into the graph (progressive expansion) |
| Click line | select the connection → evidence sentences, then sources on demand |
| Connect / Ask returns a path | **showPath** adds missing nodes/edges, highlights the path, dims the rest, auto-fits after layout settles |
| Filter chips / slider | re-fetch the current center with the new relationship categories / limit |

Readability ("no hairball") measures: hard node caps (API ≤ 150 per request; client stops expanding at 400
artists); edges not touching the focused artist drawn at low opacity; labels only for seeds, the center, the path,
the selection and the top-degree hubs (others on hover), drawn in a separate top layer so circles never cover
text; stronger node repulsion; Fit capped at 1.2× zoom.

Positions persist across updates (kept in a ref map; new nodes spawn next to a known neighbor), so expansions don't
reshuffle the layout the user has already read.

## State flow

```
user action ─▶ api.* (typed) ─▶ dispatch({reset|merge|showPath|select}) ─▶ graphReducer (pure)
                                                             │
                   GraphCanvas (nodes, edges, selection, path) ◀─┴─▶ right panel (selection → useApi fetch)
```

Server state is fetched per panel with `useApi(key, loader)` (abortable, keyed). Client state is the graph model
plus UI state (tab, filters, endpoints).

## Accessibility

Search is an ARIA combobox (arrow keys, Enter, Escape, `aria-activedescendant`). All actions are buttons with
visible focus rings. The artist panel lists the strongest connections as buttons, a keyboard-reachable alternative
to clicking graph lines. `prefers-color-scheme` gives light and dark themes, and `prefers-reduced-motion` stops the
loading animation. Known gap: the SVG graph itself is not keyboard-navigable; a full list/table view of the
current graph is Phase 2.

## Testing

Vitest: reducer behavior (reset, merge, truncation, path overlay, deterministic edge coloring) and API error
parsing. Manual/automated browser verification: the headless-browser script (search → graph, Connect → highlighted path,
Ask → grounded answer, provenance, mobile width) ran with zero console errors. Playwright E2E in CI is Phase 2.
