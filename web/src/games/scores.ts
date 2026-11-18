/**
 * Leaderboards, client side: what a play submits, whether it was already
 * submitted, and how a board is summarized. Pure and unit-tested.
 */
import type {ArtistSummary, Schemas} from '../api/client';
import type {GameState} from '../play/game';

import type {TriviaRecord} from './trivia';

type Game = Schemas['Game'];
type GameScore = Schemas['GameScore'];
type ListenerRange = Schemas['ListenerRange'];

/** The moves of a solved puzzle as the server wants them: start first, target last. */
export function puzzleMoves(
  start: Pick<ArtistSummary, 'name'>,
  game: Pick<GameState, 'chain' | 'status'>,
): string[] | null {
  if (game.status !== 'won' || game.chain.length === 0) return null;
  return [start.name, ...game.chain.map(s => s.artist.name)];
}

/** Every answer of a finished Credit check, in the order asked. */
export function triviaAnswers(
  record: TriviaRecord,
): {question: string; option: string}[] | null {
  const answers = record.order.map(id => ({
    question: id,
    option: record.answers[id]?.option ?? '',
  }));
  return answers.length > 0 && answers.every(a => a.option) ? answers : null;
}

/** The player's score for a game on a day, when they already submitted one. */
export function scoreFor(
  scores: readonly GameScore[] | undefined,
  game: Game,
  date: string,
): GameScore | undefined {
  return scores?.find(s => s.game === game && s.date === date);
}

/**
 * Whether a finished game can still go on the leaderboards: only today's game
 * (the player's local day) is scored; archive days are just for fun.
 */
export function scoreable(date: string, today: string): boolean {
  return date === today;
}

/** A player count shown as a range, never an exact number. */
export function playersRange(range: ListenerRange): {
  id: 'lb.campus.players.range' | 'lb.campus.players.open';
  values: {min: number; max?: number};
} {
  return range.max === null
    ? {id: 'lb.campus.players.open', values: {min: range.min}}
    : {id: 'lb.campus.players.range', values: {min: range.min, max: range.max}};
}

/**
 * The rows to show from a ranked list: the top `limit`, plus the viewer's own
 * row when it falls below them, so a player always sees where they stand.
 */
export function visibleRows<T>(
  rows: readonly T[],
  limit: number,
  isMine: (row: T) => boolean,
): {top: T[]; mine: T | null} {
  const top = rows.slice(0, limit);
  const mine = rows.slice(limit).find(isMine) ?? null;
  return {top, mine};
}
