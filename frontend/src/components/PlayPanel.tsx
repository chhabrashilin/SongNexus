import { useState } from "react";

import type { DailyGame } from "../hooks/useDailyGame";
import { api } from "../services/api";
import { currentDistance, shareText } from "../state/game";
import type { PathNode, PathResponse } from "../types/api";
import { CheckIcon, SparkIcon } from "./Icons";
import { PathView } from "./PathView";
import { SearchBox } from "./SearchBox";

interface Props {
  game: DailyGame;
  onExplore: (artistId: string) => void;
  onSelectEdge: (a: string, b: string) => void;
}

export function PlayPanel({ game, onExplore, onSelectEdge }: Props) {
  const { puzzle, state, current } = game;
  const [hints, setHints] = useState<PathNode[] | null>(null);
  const [solution, setSolution] = useState<PathResponse | null>(null);
  const [copied, setCopied] = useState(false);

  if (game.error && !puzzle) return <div className="panel-body error">{game.error}</div>;
  if (!puzzle || !state || !current) return <div className="panel-body muted">Loading today's puzzle…</div>;

  const distance = currentDistance(state, puzzle.par);
  const done = state.status !== "playing";

  const askHint = () => {
    game.hint().then(setHints, () => setHints([]));
  };

  const revealSolution = () => {
    api.gameSolution(puzzle.date).then(setSolution, () => setSolution(null));
  };

  const share = async () => {
    const text = shareText(state, puzzle);
    try {
      if (navigator.share) await navigator.share({ text });
      else await navigator.clipboard.writeText(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      // Share sheet dismissed or clipboard blocked: nothing to do.
    }
  };

  const pick = (artist: PathNode) => {
    setHints(null);
    game.guess(artist);
  };

  return (
    <div className="panel-body">
      <div className="panel-intro">
        <span className="eyebrow">SongNexus Daily #{puzzle.number}</span>
        <h2>
          {puzzle.start.name} <span className="muted">→</span> {puzzle.target.name}
        </h2>
        <p>
          Connect them through real collaborations, one artist at a time. Shortest possible: <strong>{puzzle.par} steps</strong>.
        </p>
      </div>

      {!done && (
        <>
          <div className="play-prompt">
            <span className="muted small">You're at</span>
            <strong>{current.name}</strong>
            <span className="distance-pill">{distance === null ? "no route from here" : `${distance} to go`}</span>
          </div>
          <SearchBox
            compact
            autoFocus
            label={`Who has ${current.name} worked with?`}
            placeholder={`Who has ${current.name} worked with?`}
            types={["artist"]}
            onPick={(r) => pick({ id: r.id, name: r.name, genres: [] })}
          />
          {game.checking && <p className="note">Checking the credits…</p>}
          {game.lastMiss && <p className="callout warn">{game.lastMiss}</p>}

          {hints && hints.length > 0 && (
            <section className="section">
              <h3>Hint: one of these gets you closer</h3>
              <div className="chips">
                {hints.map((h) => (
                  <button key={h.id} type="button" className="chip" onClick={() => pick(h)}>
                    {h.name}
                  </button>
                ))}
              </div>
            </section>
          )}

          <div className="actions three">
            <button type="button" className="btn" onClick={askHint}>
              <SparkIcon size={14} /> Hint
            </button>
            <button type="button" className="btn" onClick={game.undo} disabled={state.chain.length === 0}>
              Undo
            </button>
            <button type="button" className="btn btn-ghost" onClick={game.giveUp}>
              Give up
            </button>
          </div>
          {state.misses.length > 0 && (
            <p className="note">
              Misses: {state.misses.join(", ")}. Wrong guesses don't cost steps, but they show in your share card.
            </p>
          )}
        </>
      )}

      {done && (
        <article className="card result-card" aria-live="polite">
          {state.status === "won" ? (
            <>
              <span className="badge ok">
                <CheckIcon size={12} /> Solved
              </span>
              <span className="big-number">
                {state.chain.length}
                <small>
                  steps · par {puzzle.par}
                  {state.chain.length <= puzzle.par ? " · perfect" : ""}
                </small>
              </span>
            </>
          ) : (
            <span className="badge warn">Gave up</span>
          )}
          <pre className="share-preview">{shareText(state, puzzle)}</pre>
          <button type="button" className="btn btn-primary" onClick={share}>
            {copied ? "Copied!" : "Share result"}
          </button>
          <div className="actions">
            <button type="button" className="btn" onClick={revealSolution}>
              Shortest route
            </button>
            <button type="button" className="btn" onClick={() => onExplore(puzzle.target.id)}>
              Explore {puzzle.target.name}
            </button>
          </div>
          {solution?.path && <PathView path={solution.path} onSelectEdge={onSelectEdge} />}
          <p className="note">A new puzzle arrives every day. Same puzzle for everyone.</p>
        </article>
      )}
    </div>
  );
}
