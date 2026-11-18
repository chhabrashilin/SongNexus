import {describe, expect, it} from 'vitest';

import {
  decadeBars,
  genreSlices,
  nexusUrl,
  peakDecade,
  wholePercents,
} from './taste';

describe('wholePercents', () => {
  it('sums to 100 with the largest remainders rounded up', () => {
    expect(wholePercents([1 / 3, 1 / 3, 1 / 3])).toEqual([34, 33, 33]);
    expect(wholePercents([0.396, 0.16, 0.152, 0.292])).toEqual([
      40, 16, 15, 29,
    ]);
  });
  it('normalizes shares that do not sum to 1, and ignores negatives', () => {
    expect(wholePercents([2, 2])).toEqual([50, 50]);
    expect(wholePercents([-1, 1])).toEqual([0, 100]);
  });
  it('is all zeros for nothing', () => {
    expect(wholePercents([])).toEqual([]);
    expect(wholePercents([0, 0])).toEqual([0, 0]);
  });
});

describe('genreSlices', () => {
  const g = (name: string, share: number) => ({
    genre: `genres/${name}`,
    displayName: name,
    share,
  });
  it('names the four largest and folds the rest into "other"', () => {
    const slices = genreSlices([
      g('hip hop', 0.4),
      g('r&b', 0.2),
      g('pop', 0.15),
      g('funk', 0.1),
      g('gospel', 0.1),
      g('dance', 0.05),
    ]);
    expect(slices.map(s => s.label)).toEqual([
      'hip hop',
      'r&b',
      'pop',
      'funk',
      null,
    ]);
    expect(slices.map(s => s.percent)).toEqual([40, 20, 15, 10, 15]);
    expect(slices.at(-1)!.color).toBe('var(--neutral-soft)');
    expect(slices.reduce((sum, s) => sum + s.percent, 0)).toBe(100);
  });
  it('has no "other" when there are four genres or fewer', () => {
    expect(
      genreSlices([g('pop', 0.7), g('soul', 0.3)]).map(s => s.key),
    ).toEqual(['genres/pop', 'genres/soul']);
  });
  it('drops slices that round to zero', () => {
    expect(genreSlices([g('pop', 0.999), g('soul', 0.001)])).toHaveLength(1);
  });
});

describe('decadeBars', () => {
  it('fills the gaps between the first and last decade and marks the peak', () => {
    const bars = decadeBars([
      {decade: 1970, share: 0.2},
      {decade: 2000, share: 0.8},
    ]);
    expect(bars.map(b => b.decade)).toEqual([1970, 1980, 1990, 2000]);
    expect(bars.map(b => b.percent)).toEqual([20, 0, 0, 80]);
    expect(bars.map(b => b.peak)).toEqual([false, false, false, true]);
    expect(bars[0]!.height).toBeCloseTo(0.25);
  });
  it('is empty without decades', () => {
    expect(decadeBars([])).toEqual([]);
  });
});

describe('peakDecade', () => {
  it('finds the largest share, or null', () => {
    expect(
      peakDecade([
        {decade: 1990, share: 0.1},
        {decade: 2010, share: 0.6},
        {decade: 2000, share: 0.3},
      ]),
    ).toBe(2010);
    expect(peakDecade([])).toBeNull();
  });
});

describe('nexusUrl', () => {
  it('points at the Library section', () => {
    expect(nexusUrl('https://songnexus.app/')).toBe(
      'https://songnexus.app/library#your-nexus',
    );
  });
});
