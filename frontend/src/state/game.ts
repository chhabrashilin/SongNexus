// SongNexus Daily: pure game logic (scoring, share card), unit-tested without React.

import type { EvidenceItem, PathNode } from "../types/api";

export type Move = "closer" | "same" | "farther" | "back";

export interface Step {
  artist: PathNode;
  evidence: EvidenceItem[];
  evidenceTotal: number;
  distance: number | null;
}

export interface GameState {
  date: string;
  chain: Step[]; // accepted steps after the start artist
  moves: Move[];
  misses: string[];
  hints: number;
  status: "playing" | "won" | "gave_up";
}

export const newGame = (date: string): GameState => ({ date, chain: [], moves: [], misses: [], hints: 0, status: "playing" });

/** Distance from the current artist to the target (the start's distance is par). */
export function currentDistance(state: GameState, par: number): number | null {
  return state.chain.length ? (state.chain[state.chain.length - 1]!.distance ?? null) : par;
}

export function classifyMove(before: number | null, after: number | null): Move {
  if (after === null) return "farther";
  if (before === null) return "closer";
  return after < before ? "closer" : after === before ? "same" : "farther";
}

export function applyStep(state: GameState, step: Step, par: number, reachedTarget: boolean): GameState {
  const move = classifyMove(currentDistance(state, par), step.distance);
  return {
    ...state,
    chain: [...state.chain, step],
    moves: [...state.moves, move],
    status: reachedTarget ? "won" : state.status,
  };
}

export function applyMiss(state: GameState, name: string): GameState {
  return state.misses.includes(name) ? state : { ...state, misses: [...state.misses, name] };
}

export function undo(state: GameState): GameState {
  if (!state.chain.length || state.status !== "playing") return state;
  return { ...state, chain: state.chain.slice(0, -1), moves: [...state.moves, "back"] };
}

const EMOJI: Record<Move, string> = { closer: "🟩", same: "🟨", farther: "🟥", back: "↩️" };

/** Spoiler-free share text: shape of the game, never the artists in between. */
export function shareText(state: GameState, puzzle: { number: number; start: PathNode; target: PathNode; par: number }): string {
  const steps = state.chain.length;
  const outcome =
    state.status === "won"
      ? `${steps} step${steps === 1 ? "" : "s"} (par ${puzzle.par})`
      : `gave up after ${steps} step${steps === 1 ? "" : "s"} (par ${puzzle.par})`;
  const extras = [
    state.misses.length ? `${state.misses.length} miss${state.misses.length === 1 ? "" : "es"}` : null,
    state.hints ? `${state.hints} hint${state.hints === 1 ? "" : "s"}` : null,
  ].filter(Boolean);
  return [
    `SongNexus Daily #${puzzle.number} 🎧`,
    `${puzzle.start.name} → ${puzzle.target.name}`,
    [outcome, ...extras].join(" · "),
    state.moves.map((m) => EMOJI[m]).join("") + (state.status === "won" ? "🎯" : ""),
  ].join("\n");
}
