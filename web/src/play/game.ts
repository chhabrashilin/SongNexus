/**
 * The daily puzzle's client state (US-04): pure functions, unit-tested without React.
 *
 * Progress lives on this device (the casual puzzle is stateless on the server),
 * keyed by date and catalog version so a new catalog never resumes a stale game.
 */
import type {ArtistSummary, Evidence} from '../api/client';

export type Move = 'closer' | 'same' | 'farther' | 'back';
export type Status = 'playing' | 'won' | 'gaveUp';

export interface Step {
  artist: ArtistSummary;
  evidence: Evidence[];
  stepsToTarget: number | null;
}

export interface GameState {
  date: string;
  graphVersion: string;
  puzzleKey: string;
  finishedOn?: string;
  par?: number;
  chain: Step[];
  moves: Move[];
  misses: number;
  hints: number;
  status: Status;
}

export function newGame(
  date: string,
  graphVersion: string,
  puzzleKey = graphVersion,
): GameState {
  return {
    date,
    graphVersion,
    puzzleKey,
    chain: [],
    moves: [],
    misses: 0,
    hints: 0,
    status: 'playing',
  };
}

/** Steps left from the current artist (the start's distance is par). */
export function stepsLeft(state: GameState, par: number): number | null {
  return state.chain.length
    ? state.chain[state.chain.length - 1]!.stepsToTarget
    : par;
}

export function classifyMove(
  before: number | null,
  after: number | null,
): Move {
  if (after === null) return 'farther';
  if (before === null) return 'closer';
  return after < before ? 'closer' : after === before ? 'same' : 'farther';
}

export function applyStep(
  state: GameState,
  step: Step,
  par: number,
  reachedTarget: boolean,
  today = state.date,
): GameState {
  if (state.status !== 'playing') return state;
  return {
    ...state,
    chain: [...state.chain, step],
    moves: [
      ...state.moves,
      classifyMove(stepsLeft(state, par), step.stepsToTarget),
    ],
    status: reachedTarget ? 'won' : 'playing',
    ...(reachedTarget ? {finishedOn: today, par} : {}),
  };
}

export function applyMiss(state: GameState): GameState {
  return state.status === 'playing'
    ? {...state, misses: state.misses + 1}
    : state;
}

export function applyHint(state: GameState): GameState {
  return state.status === 'playing'
    ? {...state, hints: state.hints + 1}
    : state;
}

export function undo(state: GameState): GameState {
  if (!state.chain.length || state.status !== 'playing') return state;
  return {
    ...state,
    chain: state.chain.slice(0, -1),
    moves: [...state.moves, 'back'],
  };
}

export function giveUp(state: GameState, today = state.date): GameState {
  return state.status === 'playing'
    ? {...state, status: 'gaveUp', finishedOn: today}
    : state;
}

const SQUARES: Record<Move, string> = {
  closer: '🟩',
  same: '🟨',
  farther: '🟥',
  back: '↩️',
};

/**
 * The share text: the puzzle, the result and the shape of the game, never the
 * artists in between (plan §16.3), so sharing doesn't spoil the puzzle.
 */
export function shareText(
  state: GameState,
  puzzle: {
    number: number;
    start: ArtistSummary;
    target: ArtistSummary;
    par: number;
  },
  t: (
    id: 'play.share.won' | 'play.share.gaveUp',
    values: Record<string, number>,
  ) => string,
  link?: string,
): string {
  const result =
    state.status === 'won'
      ? t('play.share.won', {
          steps: state.chain.length,
          par: puzzle.par,
          misses: state.misses,
          hints: state.hints,
        })
      : t('play.share.gaveUp', {steps: state.chain.length, par: puzzle.par});
  return [
    `SongNexus #${puzzle.number}`,
    `${puzzle.start.displayName} → ${puzzle.target.displayName}`,
    result,
    state.moves.map(m => SQUARES[m]).join('') +
      (state.status === 'won' ? '🎯' : ''),
    ...(link ? [link] : []),
  ].join('\n');
}

export const STORAGE_KEY = 'songnexus.play.v2';

/** Calendar arithmetic in UTC avoids daylight-saving gaps in local dates. */
export function addDays(date: string, days: number): string {
  const next = new Date(`${date}T00:00:00Z`);
  next.setUTCDate(next.getUTCDate() + days);
  return next.toISOString().slice(0, 10);
}

export const LAUNCH_DAY = '2026-10-07';

export function validPuzzleDate(value: string, today: string): boolean {
  return (
    /^\d{4}-\d{2}-\d{2}$/.test(value) &&
    value >= LAUNCH_DAY &&
    value <= today &&
    Number.isFinite(Date.parse(value)) &&
    addDays(value, 0) === value
  );
}

/** Canonical v2 route; query parameters for other screens retain their own routes. */
export function puzzleLink(origin: string, date: string): string {
  return new URL(`/play?date=${encodeURIComponent(date)}`, origin).href;
}

function validGame(value: unknown): value is GameState {
  if (!value || typeof value !== 'object') return false;
  const game = value as GameState;
  return (
    typeof game.date === 'string' &&
    validPuzzleDate(game.date, '9999-12-31') &&
    typeof game.graphVersion === 'string' &&
    typeof game.puzzleKey === 'string' &&
    ['playing', 'won', 'gaveUp'].includes(game.status) &&
    Number.isInteger(game.misses) &&
    game.misses >= 0 &&
    Number.isInteger(game.hints) &&
    game.hints >= 0 &&
    Array.isArray(game.moves) &&
    game.moves.every(m => Object.hasOwn(SQUARES, m)) &&
    Array.isArray(game.chain) &&
    game.chain.every(
      s =>
        s &&
        typeof s.artist?.name === 'string' &&
        typeof s.artist.displayName === 'string' &&
        Array.isArray(s.evidence) &&
        s.evidence.every(
          e =>
            e &&
            typeof e.subject?.name === 'string' &&
            (e.subject.displayName === null ||
              typeof e.subject.displayName === 'string') &&
            typeof e.fromArtist === 'string' &&
            typeof e.toArtist === 'string' &&
            typeof e.messageId === 'string' &&
            typeof e.fromRole === 'string' &&
            typeof e.toRole === 'string' &&
            Array.isArray(e.sources) &&
            e.sources.every(source => source && typeof source.url === 'string'),
        ) &&
        (s.stepsToTarget === null ||
          (Number.isInteger(s.stepsToTarget) && s.stepsToTarget >= 0)),
    )
  );
}

/** Malformed or unavailable storage cannot prevent playing. */
export function loadGames(
  storage: Pick<Storage, 'getItem'> | null,
): GameState[] {
  try {
    const value: unknown = JSON.parse(storage?.getItem(STORAGE_KEY) ?? '[]');
    return Array.isArray(value) ? value.filter(validGame) : [];
  } catch {
    return [];
  }
}

/** Restores today's game for this catalog version, or starts a new one. */
export function loadGame(
  date: string,
  graphVersion: string,
  storage: Pick<Storage, 'getItem'> | null,
  puzzleKey = graphVersion,
): GameState {
  return (
    loadGames(storage).find(
      g =>
        g.date === date &&
        g.graphVersion === graphVersion &&
        g.puzzleKey === puzzleKey,
    ) ?? newGame(date, graphVersion, puzzleKey)
  );
}

export function saveGame(
  state: GameState,
  storage: Pick<Storage, 'getItem' | 'setItem'> | null,
): void {
  try {
    const games = loadGames(storage).filter(g => g.date !== state.date);
    storage?.setItem(STORAGE_KEY, JSON.stringify([...games, state]));
  } catch {
    // Storage full or blocked: the game still works for this visit.
  }
}

/** Archive wins count toward totals, but only wins on the puzzle's day earn a streak. */
export function computeStats(games: GameState[], today: string) {
  const byDate = new Map(
    games.filter(g => g.date <= today).map(g => [g.date, g]),
  );
  const finished = [...byDate.values()].filter(g => g.status !== 'playing');
  const wins = finished.filter(g => g.status === 'won');
  const onDay = (g: GameState | undefined) =>
    g?.status === 'won' && g.finishedOn === g.date;
  let currentStreak = 0;
  if (byDate.get(today)?.status !== 'gaveUp') {
    let day = onDay(byDate.get(today)) ? today : addDays(today, -1);
    while (onDay(byDate.get(day))) {
      currentStreak++;
      day = addDays(day, -1);
    }
  }
  let maxStreak = 0;
  let run = 0;
  let previous = '';
  for (const day of [...byDate.keys()].sort()) {
    if (!onDay(byDate.get(day))) {
      run = 0;
      previous = '';
      continue;
    }
    run = previous && addDays(previous, 1) === day ? run + 1 : 1;
    previous = day;
    maxStreak = Math.max(maxStreak, run);
  }
  return {
    played: finished.length,
    won: wins.length,
    winRate: finished.length
      ? Math.round((100 * wins.length) / finished.length)
      : 0,
    perfect: wins.filter(g => g.par !== undefined && g.chain.length <= g.par)
      .length,
    currentStreak,
    maxStreak,
  };
}

/** The player's local calendar date (puzzles follow local midnight, not UTC). */
export function localDate(now: Date = new Date()): string {
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}
