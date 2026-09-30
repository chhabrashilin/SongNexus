import { useState } from "react";

import { api } from "../services/api";
import type { AgentResponse, PathOut } from "../types/api";
import { AlertIcon, CheckIcon, SparkIcon } from "./Icons";
import { PathView } from "./PathView";

const EXAMPLES = [
  "How is Miles Davis connected to Drake?",
  "Who produced for Kendrick Lamar?",
  "Which artists bridge different scenes?",
  "How are Paul McCartney and Billie Eilish connected?",
];

/** Template answers list the path steps in text; the timeline below shows them richer, so drop the duplicate lines. */
function answerText(response: AgentResponse): string {
  if (response.answer_source !== "template" || !response.path) return response.answer;
  return response.answer
    .split("\n")
    .filter((line) => !/^\d+\.\s/.test(line))
    .join("\n");
}

interface Props {
  onShowPath: (path: PathOut) => void;
  onSelectEdge: (a: string, b: string) => void;
}

export function AskPanel({ onShowPath, onSelectEdge }: Props) {
  const [question, setQuestion] = useState("");
  const [response, setResponse] = useState<AgentResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const ask = (q: string) => {
    const text = q.trim();
    if (!text) return;
    setQuestion(text);
    setLoading(true);
    setError(null);
    api.ask(text).then(
      (r) => {
        setResponse(r);
        setLoading(false);
        if (r.path) onShowPath(r.path);
      },
      (err: unknown) => {
        setError(err instanceof Error ? err.message : "The assistant failed");
        setLoading(false);
      },
    );
  };

  return (
    <div className="panel-body">
      <div className="panel-intro">
        <h2>Ask</h2>
        <p>Ask in plain language. Answers are computed from the graph, and the evidence is shown with them.</p>
      </div>
      <form
        className="ask-form"
        onSubmit={(e) => {
          e.preventDefault();
          ask(question);
        }}
      >
        <label htmlFor="ask-input" className="sr-only">
          Ask about artist connections
        </label>
        <textarea
          id="ask-input"
          value={question}
          maxLength={500}
          rows={2}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              ask(question);
            }
          }}
          placeholder="How is Daft Punk connected to Kamasi Washington?"
        />
        <button type="submit" className="btn btn-primary" disabled={loading || !question.trim()}>
          <SparkIcon size={15} />
          {loading ? "Working it out…" : "Ask"}
        </button>
      </form>

      {!response && (
        <section className="section">
          <h3>Try</h3>
          <div className="chips">
            {EXAMPLES.map((q) => (
              <button key={q} type="button" className="chip" onClick={() => ask(q)}>
                {q}
              </button>
            ))}
          </div>
        </section>
      )}
      {error && <p className="error">{error}</p>}

      {response && (
        <article className="card" aria-live="polite">
          <div className="badges">
            <span className="badge">{response.mode_used === "llm" ? "Explained by Claude" : "Deterministic planner"}</span>
            {response.grounding.verified ? (
              <span className="badge ok">
                <CheckIcon size={12} /> Grounded in graph data
              </span>
            ) : (
              <span className="badge warn">
                <AlertIcon size={12} /> Check limitations
              </span>
            )}
          </div>
          <p className="answer">{answerText(response)}</p>
          {response.path && <PathView path={response.path} onSelectEdge={onSelectEdge} />}
          {response.limitations.length > 0 && (
            <div className="callout warn">
              <div className="callout-title">
                <AlertIcon size={14} /> Limitations
              </div>
              <ul>
                {response.limitations.map((l) => (
                  <li key={l}>{l}</li>
                ))}
              </ul>
            </div>
          )}
          <details className="trace">
            <summary>
              How this answer was computed ({response.tools_used.length} tool call{response.tools_used.length === 1 ? "" : "s"})
            </summary>
            <ol>
              {response.tools_used.map((t) => (
                <li key={t.step} className={t.ok ? "" : "err"}>
                  <code>{t.tool}</code> {t.summary} <span className="meta">{t.latency_ms.toFixed(1)} ms</span>
                </li>
              ))}
            </ol>
            <p className="meta">
              trace {response.trace_id} · {response.elapsed_ms.toFixed(0)} ms
              {response.intent ? ` · intent ${response.intent}` : ""}
            </p>
          </details>
        </article>
      )}
    </div>
  );
}
