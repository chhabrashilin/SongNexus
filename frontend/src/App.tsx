import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";

import { AskPanel } from "./components/AskPanel";
import { ConnectPanel } from "./components/ConnectPanel";
import { ArtistPanel, EdgePanel, TrackPanel } from "./components/DetailPanels";
import { FilterBar } from "./components/FilterBar";
import { GameBoard } from "./components/GameBoard";
import { BrandMark, CloseIcon, MoonIcon, SunIcon } from "./components/Icons";
import { PlayPanel } from "./components/PlayPanel";
import { SearchBox } from "./components/SearchBox";
import { GraphCanvas } from "./graph/GraphCanvas";
import { useDailyGame } from "./hooks/useDailyGame";
import { api } from "./services/api";
import { MAX_VISIBLE_NODES, emptyGraph, graphReducer } from "./state/graphState";
import { DEFAULT_CATEGORIES, type Category, type GraphStats, type PathNode, type PathOut, type SearchResult } from "./types/api";

type Tab = "play" | "explore" | "connect" | "ask";
type Theme = "dark" | "light";

const FEATURED = ["Kendrick Lamar", "Herbie Hancock", "Daft Punk", "Taylor Swift", "Thundercat"];
const EXPAND_LIMIT = 15;
const THEME_KEY = "songnexus.theme";
const TAB_LABELS: Record<Tab, string> = { play: "Play", explore: "Explore", connect: "Connect", ask: "Ask" };

// Theme is a per-viewer convenience; storage may be unavailable (private mode), so never depend on it.
function readTheme(): Theme {
  try {
    return window.localStorage.getItem(THEME_KEY) === "light" ? "light" : "dark";
  } catch {
    return "dark";
  }
}

export default function App() {
  const [graph, dispatch] = useReducer(graphReducer, emptyGraph);
  const [tab, setTabState] = useState<Tab>("explore");
  // The daily game loads the first time Play opens, then keeps its state for the visit.
  const [playOpened, setPlayOpened] = useState(false);
  const setTab = (next: Tab) => {
    if (next === "play") setPlayOpened(true);
    setTabState(next);
  };
  const game = useDailyGame(playOpened);
  const [categories, setCategories] = useState<Category[]>(DEFAULT_CATEGORIES);
  const [limit, setLimit] = useState(30);
  const [track, setTrack] = useState<string | null>(null);
  const [endpoints, setEndpoints] = useState<{ from: PathNode | null; to: PathNode | null }>({ from: null, to: null });
  const [stats, setStats] = useState<GraphStats | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [theme, setTheme] = useState<Theme>(readTheme);
  const searchRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    api.stats().then(setStats, () => setStats(null));
  }, []);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try {
      window.localStorage.setItem(THEME_KEY, theme);
    } catch {
      // Storage unavailable: the theme still applies for this visit.
    }
  }, [theme]);

  // "/" focuses search from anywhere except text fields.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const typing = target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable);
      if (event.key === "/" && !typing) {
        event.preventDefault();
        searchRef.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const fail = (err: unknown) => {
    setError(err instanceof Error ? err.message : "Something went wrong");
    setBusy(false);
  };

  const openArtist = useCallback(
    (id: string, cats: Category[] = categories, lim: number = limit) => {
      setBusy(true);
      setTrack(null);
      api.neighbors(id, { categories: cats, limit: lim }).then((payload) => {
        dispatch({ type: "reset", payload });
        setBusy(false);
      }, fail);
    },
    [categories, limit],
  );

  const expand = useCallback(
    (id: string) => {
      if (Object.keys(graph.nodes).length >= MAX_VISIBLE_NODES) {
        setError(`The graph already shows ${MAX_VISIBLE_NODES} artists. Recenter to keep it readable.`);
        return;
      }
      setBusy(true);
      api.neighbors(id, { categories, limit: EXPAND_LIMIT }).then((payload) => {
        dispatch({ type: "merge", payload });
        dispatch({ type: "select", selection: { kind: "artist", id } });
        setBusy(false);
      }, fail);
    },
    [categories, graph.nodes],
  );

  // Changing filters re-fetches the current center so the view matches them.
  const changeCategories = (next: Category[]) => {
    setCategories(next);
    if (graph.centerId) openArtist(graph.centerId, next, limit);
  };
  const changeLimit = (next: number) => {
    setLimit(next);
    if (graph.centerId) openArtist(graph.centerId, categories, next);
  };

  const onPick = (result: SearchResult) => {
    if (result.entity_type === "artist") {
      openArtist(result.id);
      setTab("explore");
      return;
    }
    // Tracks: show credits and center the graph on the first primary artist.
    api.track(result.id).then((detail) => {
      const primary = detail.credits.find((c) => c.role === "primary");
      if (primary) openArtist(primary.artist_id);
      setTrack(detail.id);
    }, fail);
  };

  const openFeatured = (name: string) => {
    api.search(name, undefined, ["artist"], 1).then((r) => {
      const hit = r.results[0];
      if (hit) openArtist(hit.id);
    }, fail);
  };

  const showPath = useCallback((path: PathOut) => dispatch({ type: "showPath", path }), []);
  const clearPath = useCallback(() => dispatch({ type: "clearPath" }), []);

  const selectEdge = useCallback((a: string, b: string) => {
    setTrack(null);
    dispatch({ type: "select", selection: { kind: "edge", a, b } });
  }, []);

  const selectNode = useCallback((id: string) => {
    setTrack(null);
    dispatch({ type: "select", selection: { kind: "artist", id } });
  }, []);

  const connect = (node: PathNode, end: "from" | "to") => {
    setEndpoints((e) => ({ ...e, [end]: node }));
    setTab("connect");
  };

  const nodes = useMemo(() => Object.values(graph.nodes), [graph.nodes]);
  const edges = useMemo(() => Object.values(graph.edges), [graph.edges]);

  const selectedArtist = graph.selection?.kind === "artist" ? graph.selection.id : null;
  const neighbors = useMemo(() => {
    if (!selectedArtist) return [];
    return edges
      .filter((e) => e.source === selectedArtist || e.target === selectedArtist)
      .map((edge) => {
        const otherId = edge.source === selectedArtist ? edge.target : edge.source;
        return { edge, otherId, otherName: graph.nodes[otherId]?.name ?? otherId };
      });
  }, [edges, graph.nodes, selectedArtist]);

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <BrandMark />
          <span className="brand-name">SongNexus</span>
        </div>
        <SearchBox
          ref={searchRef}
          label="Search artists and songs"
          placeholder="Search artists or songs"
          types={["artist", "track"]}
          onPick={onPick}
          shortcut="/"
        />
        <div className="topbar-actions">
          <nav className="seg" aria-label="Mode">
            {(Object.keys(TAB_LABELS) as Tab[]).map((t) => (
              <button key={t} type="button" className={tab === t ? "on" : ""} aria-pressed={tab === t} onClick={() => setTab(t)}>
                {TAB_LABELS[t]}
              </button>
            ))}
          </nav>
          <button
            type="button"
            className="icon-btn"
            aria-label={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
            onClick={() => setTheme((t) => (t === "dark" ? "light" : "dark"))}
          >
            {theme === "dark" ? <SunIcon /> : <MoonIcon />}
          </button>
        </div>
      </header>

      {error && (
        <div className="toast" role="alert">
          {error}
          <button type="button" className="icon-btn plain" aria-label="Dismiss" onClick={() => setError(null)}>
            <CloseIcon size={14} />
          </button>
        </div>
      )}

      <main className="layout">
        <aside className="side left" aria-label="Controls">
          {tab === "play" && (
            <PlayPanel
              game={game}
              onExplore={(id) => {
                setTab("explore");
                openArtist(id);
              }}
              onSelectEdge={selectEdge}
            />
          )}
          {tab === "explore" && (
            <div className="panel-body">
              <div className="panel-intro">
                <h2>Explore</h2>
                <p>
                  Search an artist to see who they've worked with. Click a node for details, double-click to expand, and
                  click a line to see why two artists are connected.
                </p>
              </div>
              <FilterBar categories={categories} onChange={changeCategories} limit={limit} onLimitChange={changeLimit} />
            </div>
          )}
          {tab === "connect" && (
            <ConnectPanel
              from={endpoints.from}
              to={endpoints.to}
              categories={categories}
              onChange={(end, node) => setEndpoints((e) => ({ ...e, [end]: node }))}
              onSwap={() => setEndpoints((e) => ({ from: e.to, to: e.from }))}
              onShowPath={showPath}
              onSelectEdge={selectEdge}
            />
          )}
          {tab === "ask" && <AskPanel onShowPath={showPath} onSelectEdge={selectEdge} />}
        </aside>

        <section className="stage" aria-busy={busy}>
          {tab === "play" ? (
            <GameBoard game={game} />
          ) : nodes.length === 0 ? (
            <EmptyState onPick={openFeatured} onPlay={() => setTab("play")} />
          ) : (
            <GraphCanvas
              nodes={nodes}
              edges={edges}
              centerId={graph.centerId}
              selection={graph.selection}
              path={graph.path}
              categories={categories}
              onSelectNode={selectNode}
              onExpandNode={expand}
              onSelectEdge={selectEdge}
              onClearPath={clearPath}
            />
          )}
          {busy && <div className="loading-bar" aria-hidden="true" />}
        </section>

        <aside className="side right" aria-label="Details">
          {track ? (
            <TrackPanel id={track} onOpenArtist={(id) => openArtist(id)} />
          ) : graph.selection?.kind === "artist" ? (
            <ArtistPanel
              id={graph.selection.id}
              neighbors={neighbors}
              truncated={graph.truncated[graph.selection.id]}
              onExpand={expand}
              onRecenter={(id) => openArtist(id)}
              onSelectEdge={selectEdge}
              onConnect={connect}
            />
          ) : graph.selection?.kind === "edge" ? (
            <EdgePanel a={graph.selection.a} b={graph.selection.b} categories={categories} onSelectArtist={selectNode} />
          ) : tab === "play" ? (
            <div className="panel-body">
              <div className="panel-intro">
                <h3>How to play</h3>
                <p>Name an artist who worked directly with the current one: performed with, produced, played on, sampled or shared a band.</p>
                <p>Each right answer shows the real credit behind it and how many steps are left. Wrong guesses cost nothing but show up in your share card.</p>
                <p>Stuck? A hint offers three collaborators, and at least one of them gets you closer.</p>
              </div>
            </div>
          ) : (
            <div className="panel-body">
              <div className="panel-intro">
                <h3>Details</h3>
                <p>Select an artist or a connection to see details, evidence, and sources.</p>
              </div>
            </div>
          )}
        </aside>
      </main>

      <footer className="footer">
        {stats ? (
          <>
            <span>
              <strong>{stats.artists.toLocaleString()}</strong> artists
            </span>
            <span>
              <strong>{stats.edges.toLocaleString()}</strong> connections
            </span>
            <span>
              <strong>{stats.hydrated_artists}</strong> fully loaded discographies
            </span>
            <span>data: MusicBrainz (CC0)</span>
            <span>graph {stats.graph_version}</span>
          </>
        ) : (
          <span>Loading dataset…</span>
        )}
      </footer>
    </div>
  );
}

function EmptyState({ onPick, onPlay }: { onPick: (name: string) => void; onPlay: () => void }) {
  return (
    <div className="empty-state">
      <EmptyArt />
      <span className="eyebrow">Music knowledge graph</span>
      <h1>How is everyone in music connected?</h1>
      <p>See who performed, produced, played on, and sampled whose songs, with the source behind every link.</p>
      <button type="button" className="btn btn-primary" onClick={onPlay}>
        Play today's puzzle
      </button>
      <span className="muted small">or start exploring from an artist</span>
      <div className="chips center">
        {FEATURED.map((name) => (
          <button key={name} type="button" className="chip large" onClick={() => onPick(name)}>
            {name}
          </button>
        ))}
      </div>
    </div>
  );
}

/** Decorative constellation using the same visual language as the graph. */
function EmptyArt() {
  const nodes: [number, number, number, string][] = [
    [60, 70, 7, "var(--neutral-strong)"],
    [150, 40, 5, "var(--surface-3)"],
    [180, 110, 9, "var(--accent)"],
    [270, 60, 6, "var(--neutral-strong)"],
    [300, 130, 5, "var(--surface-3)"],
    [100, 140, 5, "var(--surface-3)"],
  ];
  const links: [number, number, string, string | undefined][] = [
    [0, 2, "var(--series-1)", undefined],
    [1, 2, "var(--series-2)", undefined],
    [2, 3, "var(--series-3)", undefined],
    [3, 4, "var(--neutral-strong)", "6 4"],
    [2, 5, "var(--series-1)", undefined],
    [0, 1, "var(--neutral-soft)", "2 4"],
  ];
  return (
    <svg className="empty-art" viewBox="0 0 360 180" aria-hidden="true">
      {links.map(([a, b, color, dash]) => {
        const [x1, y1] = nodes[a]!;
        const [x2, y2] = nodes[b]!;
        return (
          <line key={`${a}-${b}`} x1={x1} y1={y1} x2={x2} y2={y2} stroke={color} strokeWidth="2.5" strokeLinecap="round" strokeDasharray={dash} strokeOpacity="0.8" />
        );
      })}
      {nodes.map(([x, y, r, fill]) => (
        <circle key={`${x}-${y}`} cx={x} cy={y} r={r} fill={fill} stroke="var(--bg)" strokeWidth="2" />
      ))}
    </svg>
  );
}
