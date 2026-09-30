import { useCallback, useEffect, useState } from "react";

import { api } from "../services/api";
import { applyMiss, applyStep, newGame, undo as undoStep, type GameState } from "../state/game";
import type { DailyPuzzle, PathNode } from "../types/api";

const STORAGE_PREFIX = "songnexus.daily.";

// Progress is a per-viewer convenience; storage can be unavailable, and the game must still work.
function loadProgress(date: string): GameState | null {
  try {
    const raw = window.localStorage.getItem(STORAGE_PREFIX + date);
    return raw ? (JSON.parse(raw) as GameState) : null;
  } catch {
    return null;
  }
}

function saveProgress(state: GameState): void {
  try {
    window.localStorage.setItem(STORAGE_PREFIX + state.date, JSON.stringify(state));
  } catch {
    // Unavailable storage: progress lasts for this visit only.
  }
}

export interface DailyGame {
  puzzle: DailyPuzzle | null;
  state: GameState | null;
  current: PathNode | null;
  error: string | null;
  checking: boolean;
  lastMiss: string | null;
  guess: (artist: PathNode) => void;
  hint: () => Promise<PathNode[]>;
  undo: () => void;
  giveUp: () => void;
  loadDay: (date?: string) => void;
}

export function useDailyGame(active: boolean): DailyGame {
  const [puzzle, setPuzzle] = useState<DailyPuzzle | null>(null);
  const [state, setState] = useState<GameState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [checking, setChecking] = useState(false);
  const [lastMiss, setLastMiss] = useState<string | null>(null);
  const [requested, setRequested] = useState<string | undefined>(undefined);

  // Fetch lazily, the first time Play opens (and whenever a different day is requested).
  useEffect(() => {
    if (!active) return;
    let cancelled = false;
    api.daily(requested).then(
      (p) => {
        if (cancelled) return;
        setPuzzle(p);
        setState(loadProgress(p.date) ?? newGame(p.date));
        setLastMiss(null);
        setError(null);
      },
      (err: unknown) => !cancelled && setError(err instanceof Error ? err.message : "Could not load today's puzzle"),
    );
    return () => {
      cancelled = true;
    };
  }, [active, requested]);

  useEffect(() => {
    if (state) saveProgress(state);
  }, [state]);

  const current = puzzle && state ? (state.chain[state.chain.length - 1]?.artist ?? puzzle.start) : null;

  const guess = useCallback(
    (artist: PathNode) => {
      if (!puzzle || !state || !current || state.status !== "playing") return;
      if (artist.id === current.id) return;
      setChecking(true);
      api.gameCheck(current.id, artist.id, puzzle.target.id).then(
        (result) => {
          setChecking(false);
          if (!result.connected) {
            setLastMiss(`${result.artist.name} isn't directly connected to ${current.name} in the dataset.`);
            setState((s) => (s ? applyMiss(s, result.artist.name) : s));
            return;
          }
          setLastMiss(null);
          setState((s) =>
            s
              ? applyStep(
                  s,
                  {
                    artist: result.artist,
                    evidence: result.evidence,
                    evidenceTotal: result.evidence_total,
                    distance: result.distance_to_target,
                  },
                  puzzle.par,
                  result.reached_target,
                )
              : s,
          );
        },
        (err: unknown) => {
          setChecking(false);
          setError(err instanceof Error ? err.message : "Check failed");
        },
      );
    },
    [puzzle, state, current],
  );

  const hint = useCallback(async () => {
    if (!puzzle || !current) return [];
    const result = await api.gameHint(current.id, puzzle.target.id);
    setState((s) => (s ? { ...s, hints: s.hints + 1 } : s));
    return result.candidates;
  }, [puzzle, current]);

  return {
    puzzle,
    state,
    current,
    error,
    checking,
    lastMiss,
    guess,
    hint,
    undo: () => setState((s) => (s ? undoStep(s) : s)),
    giveUp: () => setState((s) => (s && s.status === "playing" ? { ...s, status: "gave_up" } : s)),
    loadDay: (date?: string) => setRequested(date),
  };
}
