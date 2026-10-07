/**
 * The Explore graph on the client: merged pages of connections plus UI state.
 * Pure functions only, so expansion, caps and "show more" are unit-tested
 * independently of canvas, d3 and React.
 */
import type {ArtistSummary, Schemas} from '../api/client';
import {idOf} from '../api/client';

/** Above this, the web gets hard to read and slow on mid-tier phones (plan US-02). */
export const MAX_VISIBLE_NODES = 300;

export interface WebNode {
  id: string;
  name: string;
  expanded: boolean;
  genreKnown: boolean;
}

export interface WebEdge {
  key: string;
  a: string;
  b: string;
  strength: number;
  kinds: Schemas['ConnectionKind'][];
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
}

export const emptyGraph: GraphState = {
  centerId: null,
  nodes: {},
  edges: {},
  expansions: {},
  capped: 0,
};

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
  | {type: 'clear'};

function addNode(
  nodes: Record<string, WebNode>,
  artist: ArtistSummary,
): string {
  const id = idOf(artist.name);
  nodes[id] ??= {
    id,
    name: artist.displayName,
    expanded: false,
    genreKnown: artist.genreKnown ?? false,
  };
  return id;
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
    edges[key] = {
      key,
      a: sourceId,
      b: otherId,
      strength: connection.strength,
      kinds: connection.kinds,
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
        {...emptyGraph, centerId, nodes},
        centerId,
        action.page,
        false,
      );
    }
    case 'expand':
      if (!(action.id in state.nodes)) return state;
      return merge(state, action.id, action.page, action.append);
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
