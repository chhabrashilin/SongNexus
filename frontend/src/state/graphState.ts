// Client-side graph model: a merge of neighborhood payloads plus UI state.
// Pure functions only, so progressive expansion and path overlays are unit-tested
// independently of D3 and React.

import type { GraphPayload, PathOut } from "../types/api";

export const MAX_VISIBLE_NODES = 400;

export interface VisNode {
  id: string;
  name: string;
  hydrated: boolean;
  genres: string[];
  degree: number;
  expanded: boolean;
}

export interface VisEdge {
  key: string;
  source: string;
  target: string;
  strength: number;
  kinds: Record<string, number>;
}

export type Selection = { kind: "artist"; id: string } | { kind: "edge"; a: string; b: string } | null;

export interface PathOverlay {
  nodes: string[];
  edgeKeys: string[];
}

export interface GraphState {
  nodes: Record<string, VisNode>;
  edges: Record<string, VisEdge>;
  centerId: string | null;
  selection: Selection;
  path: PathOverlay | null;
  truncated: Record<string, { shown: number; total: number }>;
}

export type GraphAction =
  | { type: "reset"; payload: GraphPayload }
  | { type: "merge"; payload: GraphPayload }
  | { type: "select"; selection: Selection }
  | { type: "showPath"; path: PathOut }
  | { type: "clearPath" }
  | { type: "clear" };

export const emptyGraph: GraphState = {
  nodes: {},
  edges: {},
  centerId: null,
  selection: null,
  path: null,
  truncated: {},
};

export function edgeKey(a: string, b: string): string {
  return a < b ? `${a}|${b}` : `${b}|${a}`;
}

function mergePayload(state: GraphState, payload: GraphPayload): GraphState {
  const nodes = { ...state.nodes };
  for (const n of payload.nodes) {
    const existing = nodes[n.id];
    nodes[n.id] = {
      id: n.id,
      name: n.name,
      hydrated: n.hydrated,
      genres: n.genres,
      degree: n.degree,
      expanded: (existing?.expanded ?? false) || n.id === payload.center,
    };
  }
  const edges = { ...state.edges };
  for (const e of payload.edges) {
    const key = edgeKey(e.source, e.target);
    edges[key] = { key, source: e.source, target: e.target, strength: e.strength, kinds: e.kinds };
  }
  const shown = payload.nodes.filter((n) => n.depth === 1).length;
  return {
    ...state,
    nodes,
    edges,
    truncated: { ...state.truncated, [payload.center]: { shown, total: payload.total_neighbors } },
  };
}

function overlayPath(state: GraphState, path: PathOut): GraphState {
  const nodes = { ...state.nodes };
  for (const n of path.nodes) {
    nodes[n.id] ??= { id: n.id, name: n.name, hydrated: false, genres: n.genres, degree: 0, expanded: false };
  }
  const edges = { ...state.edges };
  const edgeKeys: string[] = [];
  for (const hop of path.hops) {
    const key = edgeKey(hop.source, hop.target);
    edgeKeys.push(key);
    if (!edges[key]) {
      const kinds: Record<string, number> = {};
      for (const ev of hop.evidence) kinds[ev.kind] = (kinds[ev.kind] ?? 0) + 1;
      edges[key] = { key, source: hop.source, target: hop.target, strength: hop.strength, kinds };
    }
  }
  return { ...state, nodes, edges, path: { nodes: path.nodes.map((n) => n.id), edgeKeys } };
}

export function graphReducer(state: GraphState, action: GraphAction): GraphState {
  switch (action.type) {
    case "reset":
      return {
        ...mergePayload(emptyGraph, action.payload),
        centerId: action.payload.center,
        selection: { kind: "artist", id: action.payload.center },
      };
    case "merge":
      return mergePayload(state, action.payload);
    case "select":
      return { ...state, selection: action.selection };
    case "showPath":
      return overlayPath(state, action.path);
    case "clearPath":
      return { ...state, path: null };
    case "clear":
      return emptyGraph;
  }
}

/** Primary relationship kind of an edge, used for its color. */
export function dominantKind(edge: VisEdge): string {
  let best = "";
  let count = -1;
  for (const [kind, n] of Object.entries(edge.kinds)) {
    if (n > count || (n === count && kind < best)) {
      best = kind;
      count = n;
    }
  }
  return best;
}
