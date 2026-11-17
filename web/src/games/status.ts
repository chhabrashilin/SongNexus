/** Today's daily puzzle as the listener left it, read from the puzzle's local stats. */
import type {GameState} from '../play/game';

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
