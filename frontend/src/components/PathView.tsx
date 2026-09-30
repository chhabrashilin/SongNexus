import type { PathOut } from "../types/api";
import { kindEncoding } from "../utils/format";
import { Swatch } from "./Swatch";

interface Props {
  path: PathOut;
  onSelectEdge?: (a: string, b: string) => void;
}

/** A path as a readable story: a numbered timeline, each step with its strongest evidence. */
export function PathView({ path, onSelectEdge }: Props) {
  const names = new Map(path.nodes.map((n) => [n.id, n.name]));
  return (
    <ol className="timeline">
      {path.hops.map((hop, i) => (
        <li key={`${hop.source}-${hop.target}`}>
          <span className="step-marker" aria-hidden="true">
            {i + 1}
          </span>
          <div className="step-body">
            <div className="step-title">
              {names.get(hop.source)}
              <span className="arrow" aria-label="to">
                →
              </span>
              {names.get(hop.target)}
            </div>
            <ul className="evidence-list">
              {hop.evidence.map((e) => (
                <li key={`${e.kind}:${e.subject_id}:${e.sentence}`}>
                  <Swatch encoding={kindEncoding(e.kind)} title={e.kind_label} />
                  <span>{e.sentence}</span>
                </li>
              ))}
            </ul>
            {onSelectEdge && (
              <button type="button" className="link-btn subtle" onClick={() => onSelectEdge(hop.source, hop.target)}>
                {hop.evidence_total > hop.evidence.length
                  ? `All ${hop.evidence_total} pieces of evidence & sources`
                  : "Evidence & sources"}
              </button>
            )}
          </div>
        </li>
      ))}
    </ol>
  );
}
