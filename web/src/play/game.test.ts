import {describe, expect, it} from 'vitest';

import type {ArtistSummary} from '../api/client';
import {createI18n} from '../i18n/i18n';

import {
  applyHint,
  addDays,
  applyMiss,
  applyStep,
  classifyMove,
  computeStats,
  giveUp,
  loadGame,
  localDate,
  newGame,
  saveGame,
  STORAGE_KEY,
  puzzleLink,
  validPuzzleDate,
  shareText,
  undo,
  type Step,
} from './game';

const artist = (name: string): ArtistSummary => ({
  name: `artists/${name}`,
  displayName: name,
  disambiguation: null,
  artistType: null,
  country: null,
  genreKnown: false,
});
const step = (name: string, left: number | null): Step => ({
  artist: artist(name),
  evidence: [],
  stepsToTarget: left,
});
const puzzle = {
  number: 7,
  start: artist('Start'),
  target: artist('Target'),
  par: 3,
};

describe('game', () => {
  it('classifies moves against the steps left', () => {
    expect(classifyMove(3, 2)).toBe('closer');
    expect(classifyMove(2, 2)).toBe('same');
    expect(classifyMove(2, 3)).toBe('farther');
    expect(classifyMove(2, null)).toBe('farther');
  });

  it('plays to a win and stops accepting moves', () => {
    let state = newGame('2026-10-07', 'v1');
    state = applyStep(state, step('A', 2), 3, false);
    state = applyMiss(state);
    state = applyStep(state, step('B', 2), 3, false);
    state = undo(state);
    state = applyHint(state);
    state = applyStep(state, step('C', 1), 3, false);
    state = applyStep(state, step('Target', 0), 3, true);
    expect(state.status).toBe('won');
    expect(state.moves).toEqual(['closer', 'same', 'back', 'closer', 'closer']);
    expect(state.chain.map(s => s.artist.displayName)).toEqual([
      'A',
      'C',
      'Target',
    ]);
    expect(applyStep(state, step('X', 5), 3, false)).toBe(state);
    expect(applyMiss(state)).toBe(state);
  });

  it('gives up only while playing', () => {
    const lost = giveUp(newGame('d', 'v'));
    expect(lost.status).toBe('gaveUp');
    expect(undo(lost)).toBe(lost);
  });

  it('shares the shape of the game, never the artists in between', () => {
    const {t} = createI18n('en-US');
    let state = newGame('2026-10-07', 'v1');
    state = applyStep(state, step('Secret Middle', 2), 3, false);
    state = applyMiss(state);
    state = applyStep(state, step('Another Secret', 1), 3, false);
    state = applyStep(state, step('Target', 0), 3, true);
    const text = shareText(state, puzzle, t);
    expect(text).toBe(
      'SongNexus #7\nStart → Target\n3 steps (par 3) · 1 miss\n🟩🟩🟩🎯',
    );
    expect(text).not.toContain('Secret');
  });

  it('restores only the same day and catalog version', () => {
    const store = new Map<string, string>();
    const storage = {
      getItem: (k: string) => store.get(k) ?? null,
      setItem: (k: string, v: string) => void store.set(k, v),
    };
    const played = applyMiss(newGame('2026-10-07', 'v1'));
    saveGame(played, storage);
    expect(loadGame('2026-10-07', 'v1', storage)).toEqual(played);
    expect(loadGame('2026-10-08', 'v1', storage).misses).toBe(0);
    expect(loadGame('2026-10-07', 'v2', storage).misses).toBe(0);
    store.set(STORAGE_KEY, '{corrupt');
    expect(loadGame('2026-10-07', 'v1', storage).misses).toBe(0);
  });

  it('uses the local calendar date', () => {
    expect(localDate(new Date(2026, 0, 5, 23, 59))).toBe('2026-01-05');
  });

  it('keeps archive progress separate and rejects a replaced puzzle', () => {
    const store = new Map<string, string>();
    const storage = {
      getItem: (key: string) => store.get(key) ?? null,
      setItem: (key: string, value: string) => void store.set(key, value),
    };
    const first = applyMiss(newGame('2026-10-07', 'v1', 'A:B:3'));
    saveGame(first, storage);
    saveGame(applyHint(newGame('2026-10-08', 'v1', 'C:D:4')), storage);
    expect(loadGame('2026-10-07', 'v1', storage, 'A:B:3')).toEqual(first);
    expect(loadGame('2026-10-07', 'v1', storage, 'A:C:3').misses).toBe(0);
    expect(loadGame('2026-10-08', 'v1', storage, 'C:D:4').hints).toBe(1);
    store.set(
      STORAGE_KEY,
      JSON.stringify([{date: '2026-10-07', graphVersion: 'v1', chain: null}]),
    );
    expect(loadGame('2026-10-07', 'v1', storage).status).toBe('playing');
  });

  it('tolerates denied storage and quota errors', () => {
    const blocked = {
      getItem: () => {
        throw new Error('blocked');
      },
      setItem: () => {
        throw new Error('quota');
      },
    };
    expect(() => saveGame(newGame('2026-10-07', 'v'), blocked)).not.toThrow();
    expect(loadGame('2026-10-07', 'v', blocked).status).toBe('playing');
  });

  it('validates real archive dates and builds a dated share link', () => {
    expect(validPuzzleDate('2026-10-07', '2026-10-08')).toBe(true);
    for (const date of [
      '2026-10-06',
      '2026-10-09',
      'yesterday',
      '2027-02-30',
    ]) {
      expect(
        validPuzzleDate(
          date,
          date === '2027-02-30' ? '2027-03-02' : '2026-10-08',
        ),
      ).toBe(false);
    }
    expect(addDays('2028-03-01', -1)).toBe('2028-02-29');
    expect(addDays('2026-12-31', 1)).toBe('2027-01-01');
    const link = puzzleLink('https://songnexus.app', '2026-10-08');
    expect(link).toBe('https://songnexus.app/play?date=2026-10-08');
    expect(
      shareText(
        giveUp(newGame('2026-10-08', 'v')),
        puzzle,
        createI18n('en-US').t,
        link,
      ),
    ).toMatch(new RegExp(`${link.replace('?', '\\?')}$`));
  });
});

describe('stats', () => {
  const won = (date: string, finishedOn = date) =>
    applyStep(newGame(date, 'v'), step('Target', 0), 3, true, finishedOn);
  it('keeps yesterday’s streak while today is unfinished, and ends it on a loss or missed day', () => {
    const games = [won('2026-10-07'), won('2026-10-08')];
    expect(computeStats(games, '2026-10-09')).toEqual({
      played: 2,
      won: 2,
      winRate: 100,
      perfect: 2,
      currentStreak: 2,
      maxStreak: 2,
    });
    expect(
      computeStats([...games, newGame('2026-10-09', 'v')], '2026-10-09')
        .currentStreak,
    ).toBe(2);
    expect(
      computeStats(
        [...games, giveUp(newGame('2026-10-09', 'v'))],
        '2026-10-09',
      ),
    ).toMatchObject({played: 3, winRate: 67, currentStreak: 0, maxStreak: 2});
    expect(computeStats(games, '2026-10-10').currentStreak).toBe(0);
  });
  it('counts archive wins without earning a streak, and deduplicates dates', () => {
    const archive = won('2026-10-07', '2026-10-09');
    expect(computeStats([archive, archive], '2026-10-09')).toMatchObject({
      played: 1,
      won: 1,
      currentStreak: 0,
      maxStreak: 0,
    });
    expect(computeStats([], '2026-10-09')).toMatchObject({
      played: 0,
      winRate: 0,
      currentStreak: 0,
    });
  });
});
