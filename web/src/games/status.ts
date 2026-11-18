/**
 * Where the listener stands in today's games, read from the progress kept on
 * this device. Pure, so the hub's states are unit-tested.
 */
import {addDays, LAUNCH_DAY, type GameState} from '../play/game';

import {answeredCount, isComplete, scoreOf, type TriviaRecord} from './trivia';

export type PuzzleStatus =
  | {state: 'new'}
  | {state: 'playing'}
  | {state: 'won'; steps: number}
  | {state: 'gaveUp'};

export function puzzleStatus(games: GameState[], today: string): PuzzleStatus {
  const game = games.find(g => g.date === today);
  if (!game) return {state: 'new'};
  if (game.status === 'won') return {state: 'won', steps: game.chain.length};
  if (game.status === 'gaveUp') return {state: 'gaveUp'};
  return game.chain.length > 0 || game.misses > 0 || game.hints > 0
    ? {state: 'playing'}
    : {state: 'new'};
}

export type CreditStatus =
  | {state: 'new'}
  | {state: 'playing'; answered: number; total: number}
  | {state: 'done'; score: number; total: number};

export function creditStatus(
  records: TriviaRecord[],
  date: string,
): CreditStatus {
  const record = records.find(r => r.date === date);
  if (!record || answeredCount(record) === 0) return {state: 'new'};
  const total = record.order.length;
  return isComplete(record)
    ? {state: 'done', score: scoreOf(record), total}
    : {state: 'playing', answered: answeredCount(record), total};
}

/** How many of today's two scored games (puzzle, Credit check) are finished. */
export function finishedToday(
  puzzle: PuzzleStatus,
  credit: CreditStatus,
): number {
  return (
    (puzzle.state === 'won' || puzzle.state === 'gaveUp' ? 1 : 0) +
    (credit.state === 'done' ? 1 : 0)
  );
}

export interface ArchiveDay {
  date: string;
  /** Day of the month, for the label. */
  day: number;
  puzzle: PuzzleStatus['state'];
  isToday: boolean;
}

/**
 * The last `count` days that have a puzzle, oldest first, ending today: the
 * hub's week strip. Days before launch are left out.
 */
export function archiveDays(
  games: GameState[],
  today: string,
  count = 7,
): ArchiveDay[] {
  const days: ArchiveDay[] = [];
  for (let i = count - 1; i >= 0; i--) {
    const date = addDays(today, -i);
    if (date < LAUNCH_DAY) continue;
    days.push({
      date,
      day: Number(date.slice(8, 10)),
      puzzle: puzzleStatus(games, date).state,
      isToday: date === today,
    });
  }
  return days;
}
