import {describe, expect, it} from 'vitest';

import {
  cleanSlug,
  overlap,
  overlapShare,
  placeLabel,
  rangeParts,
  shareUrl,
  unlockProgress,
} from './format';

const row = (rank: number, name: string) => ({
  rank,
  artist: {name: `artists/${name}`, displayName: name},
});

describe('rangeParts', () => {
  it('reads a closed range', () => {
    expect(rangeParts({min: 3, max: 4})).toEqual({
      kind: 'between',
      min: 3,
      max: 4,
    });
  });
  it('reads an open-ended range', () => {
    expect(rangeParts({min: 10000, max: null})).toEqual({
      kind: 'atLeast',
      min: 10000,
      max: 10000,
    });
    expect(rangeParts({min: 10000}).kind).toBe('atLeast');
  });
});

describe('unlockProgress', () => {
  it('counts listeners so far', () => {
    expect(unlockProgress(10, 10)).toBe(0);
    expect(unlockProgress(7, 10)).toBeCloseTo(0.3);
    expect(unlockProgress(1, 10)).toBeCloseTo(0.9);
    expect(unlockProgress(0, 10)).toBe(1);
  });
  it('stays within 0 and 1', () => {
    expect(unlockProgress(15, 10)).toBe(0);
    expect(unlockProgress(-3, 10)).toBe(1);
    expect(unlockProgress(5, 0)).toBe(1);
  });
});

describe('placeLabel', () => {
  it('uses the state code in the US and the country elsewhere', () => {
    expect(placeLabel({city: 'Madison', region: 'US-WI', country: 'US'})).toBe(
      'Madison, WI',
    );
    expect(placeLabel({city: 'Toronto', region: 'CA-ON', country: 'CA'})).toBe(
      'Toronto, CA',
    );
    expect(placeLabel({city: 'Kingston', region: '', country: 'US'})).toBe(
      'Kingston, US',
    );
  });
});

describe('overlap', () => {
  it('keeps artists on both charts, best combined rank first', () => {
    const a = [row(1, 'x'), row(2, 'y'), row(3, 'z'), row(4, 'only-a')];
    const b = [row(1, 'z'), row(2, 'y'), row(5, 'x'), row(3, 'only-b')];
    expect(overlap(a, b).map(s => [s.displayName, s.rankA, s.rankB])).toEqual([
      ['y', 2, 2],
      ['z', 3, 1],
      ['x', 1, 5],
    ]);
  });
  it('is empty when nothing is shared', () => {
    expect(overlap([row(1, 'a')], [row(1, 'b')])).toEqual([]);
    expect(overlap([], [])).toEqual([]);
  });
  it('measures against the smaller chart', () => {
    expect(overlapShare(2, [1, 2, 3, 4], [1, 2])).toBe(1);
    expect(overlapShare(0, [], [1])).toBe(0);
  });
});

describe('links', () => {
  it('builds a shareable link', () => {
    expect(shareUrl('https://songnexus.app/', 'communities/uw-madison')).toBe(
      'https://songnexus.app/around-you?c=uw-madison',
    );
  });
  it('accepts only slugs from the link', () => {
    expect(cleanSlug('university-of-wisconsin-madison')).toBe(
      'university-of-wisconsin-madison',
    );
    expect(cleanSlug('../users/me')).toBeUndefined();
    expect(cleanSlug('UPPER')).toBeUndefined();
    expect(cleanSlug(null)).toBeUndefined();
  });
});
