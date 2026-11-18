/**
 * The Explore graph on the client: merged pages of connections plus UI state.
 * Pure functions only, so expansion, caps and "show more" are unit-tested
 * independently of canvas, d3 and React.
 */
import type {ArtistSummary, Schemas} from '../api/client';
import {idOf} from '../api/client';

/** Above this, the web gets hard to read and slow on mid-tier phones (plan US-02). */
export const MAX_VISIBLE_NODES = 300;
/** Undo depth: each step keeps a snapshot of the web, so it is bounded. */
export const MAX_UNDO = 25;

export interface WebNode {
  id: string;
  name: string;
  expanded: boolean;
  genreKnown: boolean;
  /** A freely licensed photo (Wikimedia Commons), when we have one. */
  image: string | null;
  /** Public ListenBrainz listener count (how widely known), when known. */
  listeners: number | null;
}

/** A song two artists share, from a connection's highlights. */
export interface WebSong {
  id: string;
  title: string;
}

export interface WebEdge {
  key: string;
  a: string;
  b: string;
  strength: number;
  /** How many credits link the two artists. */
  evidenceCount: number;
  kinds: Schemas['ConnectionKind'][];
  /** Their best-known shared songs (the server puts originals first). */
  songs: WebSong[];
}

/** Where a direct connection of the starting artist sits in the web. */
export type Orbit = 'FEATURES' | 'PRODUCTION' | 'CREDITS';
export const ORBITS: readonly Orbit[] = ['FEATURES', 'PRODUCTION', 'CREDITS'];

/** The orbit for a connection: performed together, made the music, or anything else credited. */
export function orbitOf(kinds: readonly Schemas['ConnectionKind'][]): Orbit {
  if (kinds.includes('PERFORMED_WITH')) return 'FEATURES';
  if (kinds.includes('PRODUCED_FOR') || kinds.includes('CO_PRODUCED'))
    return 'PRODUCTION';
  return 'CREDITS';
}

export interface Expansion {
  shown: number;
  total: number;
  nextPageToken: string;
}

export interface GraphState {
  centerId: string | null;
  nodes: Record<string, WebNode>;
  edges: Record<string, WebEdge>;
  expansions: Record<string, Expansion>;
  /** Connections not shown because the visible-node cap was reached. */
  capped: number;
  /** Artists expanded so far, in order (the breadcrumb trail). */
  trail: string[];
  /** Earlier webs, most recent last, for undo. */
  past: Snapshot[];
}

export type Snapshot = Omit<GraphState, 'past'>;

export const emptyGraph: GraphState = {
  centerId: null,
  nodes: {},
  edges: {},
  expansions: {},
  capped: 0,
  trail: [],
  past: [],
};

function snapshot({
  centerId,
  nodes,
  edges,
  expansions,
  capped,
  trail,
}: GraphState): Snapshot {
  return {centerId, nodes, edges, expansions, capped, trail};
}

export function edgeKey(a: string, b: string): string {
  return a < b ? `${a}|${b}` : `${b}|${a}`;
}

type Page = Pick<
  Schemas['ListArtistConnectionsResponse'],
  'connections' | 'nextPageToken' | 'totalSize'
>;

export type GraphAction =
  | {type: 'start'; center: ArtistSummary; page: Page}
  | {type: 'expand'; id: string; page: Page; append: boolean}
  | {type: 'undo'}
  | {type: 'clear'};

function addNode(
  nodes: Record<string, WebNode>,
  artist: ArtistSummary,
): string {
  const id = idOf(artist.name);
  const image = photoOf(artist);
  const listeners = listenersOf(artist);
  const known = nodes[id];
  if (!known)
    nodes[id] = {
      id,
      name: artist.displayName,
      expanded: false,
      genreKnown: artist.genreKnown ?? false,
      image,
      listeners,
    };
  // A later page can carry data an earlier one (or an older cache) lacked.
  else if ((!known.image && image) || (known.listeners === null && listeners))
    nodes[id] = {
      ...known,
      image: known.image ?? image,
      listeners: known.listeners ?? listeners,
    };
  return id;
}

/** The public listener count on an artist summary, read loosely like the photo. */
export function listenersOf(artist: object): number | null {
  const value = (artist as {listeners?: unknown}).listeners;
  return typeof value === 'number' && value > 0 ? value : null;
}

/** Shared songs named in a connection's highlights, without repeats. */
export function songsOf(
  highlights: readonly {
    subject?: {name: string; displayName?: string | null} | null;
  }[],
): WebSong[] {
  const songs: WebSong[] = [];
  const seen = new Set<string>();
  for (const highlight of highlights) {
    const subject = highlight.subject;
    if (!subject?.name.startsWith('recordings/') || !subject.displayName)
      continue;
    const key = subject.displayName.toLocaleLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    songs.push({id: idOf(subject.name), title: subject.displayName});
  }
  return songs;
}

/**
 * The photo on an artist summary. Read loosely: summaries cached before photos
 * existed have no `imageUrl` at all.
 */
export function photoOf(artist: object): string | null {
  const url = (artist as {imageUrl?: unknown}).imageUrl;
  return typeof url === 'string' && url ? url : null;
}

function merge(
  state: GraphState,
  sourceId: string,
  page: Page,
  append: boolean,
): GraphState {
  const nodes = {...state.nodes};
  const edges = {...state.edges};
  let capped = state.capped;
  let shownNow = 0;
  for (const connection of page.connections) {
    const otherId = idOf(connection.artist.name);
    const known = otherId in nodes;
    if (!known && Object.keys(nodes).length >= MAX_VISIBLE_NODES) {
      capped++;
      continue;
    }
    addNode(nodes, connection.artist);
    const key = edgeKey(sourceId, otherId);
    const songs = songsOf(connection.highlights ?? []);
    edges[key] = {
      key,
      a: sourceId,
      b: otherId,
      strength: connection.strength,
      evidenceCount: connection.evidenceCount ?? 0,
      kinds: connection.kinds,
      // Seen again from the other side: keep the songs if this page has none.
      songs: songs.length ? songs : (edges[key]?.songs ?? []),
    };
    shownNow++;
  }
  nodes[sourceId] = {...nodes[sourceId]!, expanded: true};
  const previous = append ? (state.expansions[sourceId]?.shown ?? 0) : 0;
  return {
    ...state,
    nodes,
    edges,
    capped,
    expansions: {
      ...state.expansions,
      [sourceId]: {
        shown: previous + shownNow,
        total: page.totalSize,
        nextPageToken: page.nextPageToken,
      },
    },
  };
}

export function graphReducer(
  state: GraphState,
  action: GraphAction,
): GraphState {
  switch (action.type) {
    case 'start': {
      const nodes: Record<string, WebNode> = {};
      const centerId = addNode(nodes, action.center);
      return merge(
        {...emptyGraph, centerId, nodes, trail: [centerId]},
        centerId,
        action.page,
        false,
      );
    }
    case 'expand': {
      if (!(action.id in state.nodes)) return state;
      const next = merge(state, action.id, action.page, action.append);
      const trail =
        action.append || state.trail.includes(action.id)
          ? state.trail
          : [...state.trail, action.id];
      return {
        ...next,
        trail,
        past: [...state.past, snapshot(state)].slice(-MAX_UNDO),
      };
    }
    case 'undo': {
      const previous = state.past.at(-1);
      if (!previous) return state;
      return {...previous, past: state.past.slice(0, -1)};
    }
    case 'clear':
      return emptyGraph;
  }
}

/** Share of visible artists with genre data, for the genre filter (AC-12.2). */
export function genreCoverage(state: GraphState): number | undefined {
  const all = Object.values(state.nodes);
  return all.length
    ? all.filter(n => n.genreKnown).length / all.length
    : undefined;
}

/** Neighbors of a node in the visible graph, strongest first (for the list view). */
export function neighborsOf(
  state: GraphState,
  id: string,
): {node: WebNode; edge: WebEdge}[] {
  return Object.values(state.edges)
    .filter(e => e.a === id || e.b === id)
    .map(edge => ({node: state.nodes[edge.a === id ? edge.b : edge.a]!, edge}))
    .sort(
      (x, y) =>
        y.edge.strength - x.edge.strength ||
        x.node.name.localeCompare(y.node.name),
    );
}

/** The strongest visible neighbors of a node that are not expanded yet ("expand the strongest N"). */
export function strongestUnexpanded(
  state: GraphState,
  id: string,
  count: number,
): string[] {
  return neighborsOf(state, id)
    .filter(({node}) => !node.expanded)
    .slice(0, count)
    .map(({node}) => node.id);
}
