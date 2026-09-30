import { describe, expect, it } from "vitest";

import type { GraphPayload, PathOut } from "../types/api";
import { dominantKind, edgeKey, emptyGraph, graphReducer } from "./graphState";

const node = (id: string, depth: number) => ({ id, name: id.toUpperCase(), hydrated: depth === 0, genres: [], degree: 2, depth });

const payload = (center: string, others: string[], total = others.length): GraphPayload => ({
  center,
  nodes: [node(center, 0), ...others.map((o) => node(o, 1))],
  edges: others.map((o) => ({ source: center, target: o, strength: 1, kinds: { performed_with: 1 } })),
  truncated: total > others.length,
  total_neighbors: total,
  categories: ["performance"],
  graph_version: "v1",
});

describe("graphReducer", () => {
  it("reset centers the graph and selects the center", () => {
    const state = graphReducer(emptyGraph, { type: "reset", payload: payload("a", ["b", "c"]) });
    expect(Object.keys(state.nodes).sort()).toEqual(["a", "b", "c"]);
    expect(state.centerId).toBe("a");
    expect(state.selection).toEqual({ kind: "artist", id: "a" });
    expect(state.nodes.a?.expanded).toBe(true);
    expect(state.nodes.b?.expanded).toBe(false);
  });

  it("merge expands progressively without losing existing nodes", () => {
    let state = graphReducer(emptyGraph, { type: "reset", payload: payload("a", ["b"]) });
    state = graphReducer(state, { type: "merge", payload: payload("b", ["c", "d"], 10) });
    expect(Object.keys(state.nodes).sort()).toEqual(["a", "b", "c", "d"]);
    expect(Object.keys(state.edges)).toHaveLength(3);
    expect(state.nodes.b?.expanded).toBe(true);
    expect(state.truncated.b).toEqual({ shown: 2, total: 10 });
    expect(state.centerId).toBe("a");
  });

  it("edge keys are orientation independent", () => {
    expect(edgeKey("x", "y")).toBe(edgeKey("y", "x"));
  });

  it("showPath adds missing nodes and edges and highlights them", () => {
    const state = graphReducer(emptyGraph, { type: "reset", payload: payload("a", ["b"]) });
    const path: PathOut = {
      nodes: [
        { id: "a", name: "A", genres: [] },
        { id: "z", name: "Z", genres: [] },
      ],
      hops: [
        {
          source: "a",
          target: "z",
          strength: 2,
          evidence_total: 1,
          evidence: [
            {
              kind: "produced_for",
              kind_label: "production",
              subject_type: "track",
              subject_id: "t",
              subject_title: "T",
              sentence: "Z produced A's T",
              roles: {},
            },
          ],
        },
      ],
      length: 1,
      cost: null,
    };
    const next = graphReducer(state, { type: "showPath", path });
    expect(next.nodes.z?.name).toBe("Z");
    expect(next.path).toEqual({ nodes: ["a", "z"], edgeKeys: [edgeKey("a", "z")] });
    expect(next.edges[edgeKey("a", "z")]?.kinds).toEqual({ produced_for: 1 });
    expect(graphReducer(next, { type: "clearPath" }).path).toBeNull();
  });

  it("dominantKind picks the most frequent kind deterministically", () => {
    const edge = { key: "k", source: "a", target: "b", strength: 1, kinds: { produced_for: 2, performed_with: 2, sampled: 1 } };
    expect(dominantKind(edge)).toBe("performed_with");
  });
});
