import { useState } from "react";

import { api } from "../services/api";
import type { Category, PathMode, PathNode, PathOut, PathResponse } from "../types/api";
import { initials } from "../utils/format";
import { CloseIcon, SwapIcon } from "./Icons";
import { PathView } from "./PathView";
import { SearchBox } from "./SearchBox";

interface Props {
  from: PathNode | null;
  to: PathNode | null;
  categories: Category[];
  onChange: (end: "from" | "to", node: PathNode | null) => void;
  onSwap: () => void;
  onShowPath: (path: PathOut) => void;
  onSelectEdge: (a: string, b: string) => void;
}

export function ConnectPanel({ from, to, categories, onChange, onSwap, onShowPath, onSelectEdge }: Props) {
  const [mode, setMode] = useState<PathMode>("shortest");
  const [result, setResult] = useState<PathResponse | null>(null);
  const [shown, setShown] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const run = () => {
    if (!from || !to) return;
    setLoading(true);
    setError(null);
    api.path(from.id, to.id, { mode, categories, maxDepth: 6, alternatives: 2 }).then(
      (response) => {
        setResult(response);
        setShown(0);
        setLoading(false);
        if (response.path) onShowPath(response.path);
      },
      (err: unknown) => {
        setError(err instanceof Error ? err.message : "Path search failed");
        setLoading(false);
      },
    );
  };

  const paths = result?.path ? [result.path, ...result.alternatives] : [];
  const current = paths[shown];

  return (
    <div className="panel-body">
      <div className="panel-intro">
        <h2>Connect</h2>
        <p>Pick two artists. The graph finds how they are linked, and every step is backed by a credit.</p>
      </div>

      <div className="endpoints">
        {(["from", "to"] as const).map((end) => {
          const value = end === "from" ? from : to;
          return (
            <div className="endpoint" key={end}>
              <span className="endpoint-label">{end}</span>
              {value ? (
                <span className="endpoint-chip">
                  <span className="avatar sm" aria-hidden="true">
                    {initials(value.name)}
                  </span>
                  <span className="name">{value.name}</span>
                  <button type="button" className="icon-btn plain" aria-label={`Clear ${end} artist`} onClick={() => onChange(end, null)}>
                    <CloseIcon size={14} />
                  </button>
                </span>
              ) : (
                <SearchBox
                  compact
                  label={`${end} artist`}
                  placeholder="Search an artist…"
                  types={["artist"]}
                  onPick={(r) => onChange(end, { id: r.id, name: r.name, genres: [] })}
                />
              )}
            </div>
          );
        })}
        <div className="swap-row">
          <button type="button" className="btn btn-ghost" onClick={onSwap} disabled={!from && !to}>
            <SwapIcon size={14} /> Swap
          </button>
        </div>
      </div>

      <div className="seg block" role="radiogroup" aria-label="Path mode">
        {(["shortest", "strongest"] as const).map((m) => (
          <button key={m} type="button" role="radio" aria-checked={mode === m} className={mode === m ? "on" : ""} onClick={() => setMode(m)}>
            {m === "shortest" ? "Fewest steps" : "Strongest links"}
          </button>
        ))}
      </div>
      <button type="button" className="btn btn-primary" onClick={run} disabled={!from || !to || loading}>
        {loading ? "Searching the graph…" : "Find the connection"}
      </button>
      {error && <p className="error">{error}</p>}

      {result && (
        <div className="result">
          {!result.found && <p className="callout warn">{result.explanation}</p>}
          {current && (
            <>
              <div className="result-head">
                <span className="big-number">
                  {current.length}
                  <small>step{current.length === 1 ? "" : "s"} apart</small>
                </span>
                {paths.length > 1 && (
                  <div className="seg small" role="tablist" aria-label="Routes">
                    {paths.map((p, i) => (
                      <button
                        key={p.nodes.map((n) => n.id).join("-")}
                        type="button"
                        role="tab"
                        aria-selected={i === shown}
                        className={i === shown ? "on" : ""}
                        onClick={() => {
                          setShown(i);
                          onShowPath(p);
                        }}
                      >
                        {i === 0 ? "Best" : `Alt ${i}`}
                      </button>
                    ))}
                  </div>
                )}
              </div>
              <PathView path={current} onSelectEdge={onSelectEdge} />
              <p className="meta">
                {result.algorithm} · {result.elapsed_ms.toFixed(1)} ms · graph {result.graph_version}
              </p>
            </>
          )}
        </div>
      )}
    </div>
  );
}
