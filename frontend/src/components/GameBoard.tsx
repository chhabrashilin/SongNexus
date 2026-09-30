import type { DailyGame } from "../hooks/useDailyGame";
import { currentDistance } from "../state/game";
import { initials, kindEncoding } from "../utils/format";
import { Swatch } from "./Swatch";

/** The daily puzzle's stage: the chain so far, the gap still to cross, and the target. */
export function GameBoard({ game }: { game: DailyGame }) {
  const { puzzle, state } = game;
  if (!puzzle || !state) return <div className="empty-state muted">Loading today's puzzle…</div>;
  const distance = currentDistance(state, puzzle.par);
  const won = state.status === "won";
  const steps = won ? state.chain.slice(0, -1) : state.chain;

  return (
    <div className="game-board">
      <ol className="chain">
        <ChainNode name={puzzle.start.name} role="Start" />
        {steps.map((step, i) => (
          <li key={`${step.artist.id}-${i}`} className="chain-step">
            <Link evidence={step.evidence[0]?.sentence} kind={step.evidence[0]?.kind} more={step.evidenceTotal - 1} />
            <ChainNode name={step.artist.name} role={step.distance === null ? "no route" : `${step.distance} to go`} />
          </li>
        ))}
        {won ? (
          <li className="chain-step">
            <Link
              evidence={state.chain[state.chain.length - 1]?.evidence[0]?.sentence}
              kind={state.chain[state.chain.length - 1]?.evidence[0]?.kind}
              more={(state.chain[state.chain.length - 1]?.evidenceTotal ?? 1) - 1}
            />
            <ChainNode name={puzzle.target.name} role="Target reached" highlight />
          </li>
        ) : (
          <li className="chain-step">
            <div className="chain-gap" aria-label={distance === null ? "No route from here" : `${distance} steps to go`}>
              {distance === null ? (
                <span>No route from here. Undo and try another artist.</span>
              ) : (
                <>
                  <span className="gap-dots" aria-hidden="true">
                    {Array.from({ length: Math.max(0, distance - 1) }, (_, i) => (
                      <span key={i} className="gap-dot" />
                    ))}
                  </span>
                  <span>
                    {distance === 1 ? "One more connection" : `${distance} connections to go`}
                    {state.status === "gave_up" ? " (gave up)" : ""}
                  </span>
                </>
              )}
            </div>
            <ChainNode name={puzzle.target.name} role="Target" target />
          </li>
        )}
      </ol>
    </div>
  );
}

function ChainNode({ name, role, highlight, target }: { name: string; role: string; highlight?: boolean; target?: boolean }) {
  return (
    <div className={`chain-node${highlight ? " reached" : ""}${target ? " target" : ""}`}>
      <span className="avatar" aria-hidden="true">
        {initials(name)}
      </span>
      <span className="chain-text">
        <strong>{name}</strong>
        <span className="muted small">{role}</span>
      </span>
    </div>
  );
}

function Link({ evidence, kind, more }: { evidence?: string; kind?: string; more: number }) {
  return (
    <div className="chain-link">
      <span className="chain-line" aria-hidden="true" />
      {evidence && (
        <span className="chain-evidence">
          {kind && <Swatch encoding={kindEncoding(kind)} />}
          <span>
            {evidence}
            {more > 0 && <span className="muted"> · +{more} more</span>}
          </span>
        </span>
      )}
    </div>
  );
}
