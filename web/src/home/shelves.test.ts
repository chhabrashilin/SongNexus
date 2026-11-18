import {describe, expect, it} from 'vitest';

import type {Schemas} from '../api/client';

import {curate, MAX_DECADES, MAX_GENRES, shelfDate} from './shelves';

type Shelf = Schemas['Shelf'];

function shelf(kind: Shelf['kind'], id: string, items = 1): Shelf {
  return {
    name: `shelves/${id}`,
    kind,
    messageId: 'shelf.genre',
    params: {},
    genre: null,
    items: Array.from({length: items}, (_, i) => ({
      artist: null,
      recording: null,
      label: {name: `labels/${id}-${i}`, displayName: `L${i}`},
      reason: {
        kind: 'LABEL_RELEASES',
        messageId: 'reason.labelReleases',
        params: {},
      },
    })),
  } as Shelf;
}

describe('curate', () => {
  it('drops empty shelves', () => {
    expect(curate([shelf('LABELS', 'labels', 0)])).toEqual([]);
  });

  it('leads with the editorial shelves and ends with labels', () => {
    const order = curate([
      shelf('LABELS', 'labels'),
      shelf('GENRE', 'g1'),
      shelf('SUPER_CONNECTORS', 'super'),
      shelf('ON_THIS_DAY', 'day'),
      shelf('BEHIND_THE_HITS', 'behind'),
      shelf('DECADE', 'd1'),
      shelf('GENRE_BRIDGES', 'bridges'),
    ]).map(s => s.name);
    expect(order).toEqual([
      'shelves/behind',
      'shelves/day',
      'shelves/super',
      'shelves/g1',
      'shelves/d1',
      'shelves/bridges',
      'shelves/labels',
    ]);
  });

  it('caps genres and decades and alternates them in server order', () => {
    const genres = Array.from({length: 6}, (_, i) => shelf('GENRE', `g${i}`));
    const decades = Array.from({length: 9}, (_, i) => shelf('DECADE', `d${i}`));
    const order = curate([...genres, ...decades]).map(s => s.name);
    expect(order.filter(n => n.startsWith('shelves/g'))).toHaveLength(
      MAX_GENRES,
    );
    expect(order.filter(n => n.startsWith('shelves/d'))).toHaveLength(
      MAX_DECADES,
    );
    expect(order.slice(0, 4)).toEqual([
      'shelves/g0',
      'shelves/d0',
      'shelves/g1',
      'shelves/d1',
    ]);
  });
});

describe('shelfDate', () => {
  it('reads a calendar date as that local day', () => {
    const date = shelfDate('2026-11-16');
    expect([date.getFullYear(), date.getMonth(), date.getDate()]).toEqual([
      2026, 10, 16,
    ]);
  });
});
