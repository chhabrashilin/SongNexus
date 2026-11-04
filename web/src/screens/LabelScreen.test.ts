import {describe, expect, it} from 'vitest';

import type {Schemas} from '../api/client';

import {byEra} from './LabelScreen';

const entry = (
  id: string,
  firstYear: number | null,
): Schemas['LabelArtist'] => ({
  artist: {
    name: `artists/${id}`,
    displayName: id,
    disambiguation: null,
    artistType: null,
    country: null,
    genreKnown: false,
  },
  releaseCount: 1,
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
