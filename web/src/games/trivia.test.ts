import {describe, expect, it} from 'vitest';

import {newGame, type GameState} from '../play/game';

import {archiveDays, creditStatus, finishedToday, puzzleStatus} from './status';
import {
  computeTriviaStats,
  loadRecords,
  newRecord,
  nextIndex,
  recordAnswer,
  saveRecord,
  scoreOf,
  shareText,
  type TriviaRecord,
} from './trivia';

const order = ['q1', 'q2', 'q3', 'q4', 'q5'];
const t = (
  _id: 'games.credit.share.text',
  v: {number: number; score: number; total: number},
) => `Credit check #${v.number} · ${v.score}/${v.total}`;

function played(date: string, right: boolean[], finishedOn = date) {
  let r = newRecord(date, 'v1', order);
  right.forEach((correct, i) => {
    r = recordAnswer(r, order[i]!, {option: `o${i}`, correct}, finishedOn);
  });
  return r;
}

describe('credit check record', () => {
  it('scores, orders and ignores repeat answers', () => {
    let r = newRecord('2026-11-01', 'v1', order);
    r = recordAnswer(r, 'q1', {option: 'a', correct: true}, '2026-11-01');
    r = recordAnswer(r, 'q1', {option: 'b', correct: false}, '2026-11-01');
    r = recordAnswer(r, 'zz', {option: 'b', correct: true}, '2026-11-01');
    expect(scoreOf(r)).toBe(1);
    expect(nextIndex(r)).toBe(1);
    expect(r.finishedOn).toBeUndefined();
  });

  it('share text carries the shape and never the questions', () => {
    const r = played('2026-11-01', [true, true, false, true, true]);
    expect(shareText(r, 12, t)).toBe('Credit check #12 · 4/5 🟩🟩🟥🟩🟩');
    expect(shareText(r, 12, t, 'https://x.test/games')).toContain(
      '\nhttps://x.test/games',
    );
    const partial = played('2026-11-01', [true]);
    expect(shareText(partial, 1, t)).toBe('Credit check #1 · 1/5 🟩⬜⬜⬜⬜');
  });

  it('counts a streak only for same-day finishes', () => {
    const records = [
      played('2026-11-01', [true, true, true, true, true]),
      played('2026-11-02', [true, false, true, true, true]),
      played('2026-11-03', [true, true, true, true, true], '2026-11-09'),
      played('2026-11-04', [true, true, true, true, false]),
    ];
    const stats = computeTriviaStats(records, '2026-11-04');
    expect(stats.played).toBe(4);
    expect(stats.perfect).toBe(2);
    expect(stats.average).toBe(4.5);
    expect(stats.currentStreak).toBe(1);
    expect(stats.maxStreak).toBe(2);
    expect(computeTriviaStats(records, '2026-11-05').currentStreak).toBe(1);
    expect(computeTriviaStats(records, '2026-11-06').currentStreak).toBe(0);
  });

  it('survives broken storage', () => {
    expect(loadRecords(null)).toEqual([]);
    expect(loadRecords({getItem: () => '{nope'})).toEqual([]);
    expect(loadRecords({getItem: () => '[{"date":1}]'})).toEqual([]);
    const store = new Map<string, string>();
    const storage = {
      getItem: (k: string) => store.get(k) ?? null,
      setItem: (k: string, v: string) => void store.set(k, v),
    };
    const r: TriviaRecord = played('2026-11-01', [true]);
    saveRecord(r, storage);
    saveRecord({...r, graphVersion: 'v2'}, storage);
    expect(loadRecords(storage)).toHaveLength(1);
  });
});

describe('puzzle status', () => {
  const base: GameState = newGame('2026-11-01', 'v1');
  it('reads not started, in progress, solved and revealed', () => {
    expect(puzzleStatus([], '2026-11-01')).toEqual({state: 'new'});
    expect(puzzleStatus([base], '2026-11-01')).toEqual({state: 'new'});
    expect(puzzleStatus([{...base, misses: 1}], '2026-11-01')).toEqual({
      state: 'playing',
    });
    const step = {artist: {} as never, evidence: [], stepsToTarget: 0};
    expect(
      puzzleStatus(
        [{...base, status: 'won', chain: [step, step, step]}],
        '2026-11-01',
      ),
    ).toEqual({state: 'won', steps: 3});
    expect(puzzleStatus([{...base, status: 'gaveUp'}], '2026-11-01')).toEqual({
      state: 'gaveUp',
    });
    expect(puzzleStatus([base], '2026-11-02')).toEqual({state: 'new'});
  });
});

describe('hub status', () => {
  const rec = (answers: TriviaRecord['answers']): TriviaRecord => ({
    date: '2026-11-01',
    graphVersion: 'v1',
    order: ['q1', 'q2'],
    answers,
  });
  it('reads the credit check as new, in progress or done', () => {
    expect(creditStatus([], '2026-11-01')).toEqual({state: 'new'});
    expect(creditStatus([rec({})], '2026-11-01')).toEqual({state: 'new'});
    const one = rec({q1: {option: 'a', correct: true}});
    expect(creditStatus([one], '2026-11-01')).toEqual({
      state: 'playing',
      answered: 1,
      total: 2,
    });
    const both = rec({
      q1: {option: 'a', correct: true},
      q2: {option: 'b', correct: false},
    });
    expect(creditStatus([both], '2026-11-01')).toEqual({
      state: 'done',
      score: 1,
      total: 2,
    });
    expect(
      finishedToday({state: 'gaveUp'}, {state: 'done', score: 1, total: 2}),
    ).toBe(2);
    expect(finishedToday({state: 'playing'}, {state: 'new'})).toBe(0);
  });

  it('lists the last days with a puzzle, oldest first, never before launch', () => {
    const won: GameState = {...newGame('2026-11-15', 'v1'), status: 'won'};
    const days = archiveDays([won], '2026-11-16', 3);
    expect(days.map(d => [d.date, d.puzzle, d.isToday])).toEqual([
      ['2026-11-14', 'new', false],
      ['2026-11-15', 'won', false],
      ['2026-11-16', 'new', true],
    ]);
    expect(days[2]!.day).toBe(16);
    expect(archiveDays([], '2026-10-08', 7).map(d => d.date)).toEqual([
      '2026-10-07',
      '2026-10-08',
    ]);
  });
});
