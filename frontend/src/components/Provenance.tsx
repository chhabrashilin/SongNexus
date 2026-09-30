import { useState } from "react";

import { api } from "../services/api";
import type { FactProvenance } from "../types/api";
import { hostname } from "../utils/format";

/** Loads the source facts behind a direct connection on demand. */
export function EdgeProvenance({ a, b }: { a: string; b: string }) {
  const [facts, setFacts] = useState<FactProvenance[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const load = () => {
    setLoading(true);
    api.edgeProvenance(a, b).then(
      (response) => {
        setFacts(response.facts);
        setLoading(false);
      },
      (err: unknown) => {
        setError(err instanceof Error ? err.message : "Could not load sources");
        setLoading(false);
      },
    );
  };

  if (error) return <p className="error">{error}</p>;
  if (facts === null) {
    return (
      <button type="button" className="btn" onClick={load} disabled={loading}>
        {loading ? "Loading sources…" : "Where does this come from?"}
      </button>
    );
  }
  return (
    <section className="section provenance">
      <div className="section-head">
        <h3>Source records</h3>
        <span className="meta">{facts.length} facts</span>
      </div>
      <p className="note">Every connection is computed from these records. Nothing here is generated.</p>
      {facts.map((f) => (
        <div className="fact" key={`${f.fact_type}:${f.fact_id}`}>
          <div className="fact-line">{f.description}</div>
          <div className="fact-meta">
            {f.source_urls.map((u) => (
              <a key={u} href={u} target="_blank" rel="noreferrer">
                {hostname(u)} record
              </a>
            ))}
            {f.raw_record_url && (
              <a href={f.raw_record_url} target="_blank" rel="noreferrer">
                raw API response
              </a>
            )}
            <span>retrieved {f.retrieved_at?.slice(0, 10) ?? "unknown"}</span>
            <span>pipeline {f.pipeline_version}</span>
            <span className="num">confidence {f.confidence.toFixed(2)}</span>
            <span>{f.source_license}</span>
          </div>
        </div>
      ))}
    </section>
  );
}
