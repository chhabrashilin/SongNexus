import {describe, expect, it} from 'vitest';

import type {Schemas} from '../api/client';

import {byEra, flagship} from './LabelScreen';

const entry = (
  id: string,
  firstYear: number | null,
  releaseCount = 1,
): Schemas['LabelArtist'] => ({
  artist: {
    name: `artists/${id}`,
    displayName: id,
    disambiguation: null,
    artistType: null,
    country: null,
    genreKnown: false,
    imageUrl: null,
    listeners: null,
  },
  releaseCount,
  firstYear,
  lastYear: firstYear,
});

describe('label roster by era', () => {
  it('groups by decade, oldest first, unknown years last', () => {
    const groups = byEra([
      entry('a', 1994),
      entry('b', null),
      entry('c', 1971),
      entry('d', 1999),
    ]);
    expect(
      groups.map(([decade, list]) => [
        decade,
        list.map(e => e.artist.displayName),
      ]),
    ).toEqual([
      [1970, ['c']],
      [1990, ['a', 'd']],
      [null, ['b']],
    ]);
  });
});

describe('label flagship', () => {
  it('picks the most releases, then the earliest', () => {
    expect(
      flagship([entry('a', 2001, 2), entry('b', 1999, 4), entry('c', 1990, 4)])
        ?.artist.displayName,
    ).toBe('c');
  });

  it('is null for an empty roster', () => {
    expect(flagship([])).toBeNull();
  });
});
