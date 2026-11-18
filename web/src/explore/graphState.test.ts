import {describe, expect, it} from 'vitest';

import type {Schemas} from '../api/client';

import {
  MAX_UNDO,
  MAX_VISIBLE_NODES,
  edgeKey,
  emptyGraph,
  graphReducer,
  neighborsOf,
  listenersOf,
  orbitOf,
  photoOf,
  songsOf,
  strongestUnexpanded,
} from './graphState';

const artist = (id: string): Schemas['ArtistSummary'] => ({
  name: `artists/${id}`,
  displayName: id.toUpperCase(),
  disambiguation: null,
  artistType: null,
  country: null,
  genreKnown: id < 'm',
  imageUrl: null,
  listeners: null,
});

function page(ids: string[], total = ids.length, next = '') {
  return {
    connections: ids.map((id, i) => ({
      artist: artist(id),
      strength: 10 - i,
      kinds: ['PERFORMED_WITH'] as Schemas['ConnectionKind'][],
      evidenceCount: 1,
      highlights: [],
    })),
    nextPageToken: next,
    totalSize: total,
  };
}

describe('graphReducer', () => {
  it('starts from a center artist', () => {
    const state = graphReducer(emptyGraph, {
      type: 'start',
      center: artist('k'),
      page: page(['s', 't'], 5, 'tok'),
    });
    expect(state.centerId).toBe('k');
    expect(Object.keys(state.nodes).sort()).toEqual(['k', 's', 't']);
    expect(state.nodes['k']!.expanded).toBe(true);
    expect(state.expansions['k']).toEqual({
      shown: 2,
      total: 5,
      nextPageToken: 'tok',
    });
    expect(state.edges[edgeKey('k', 's')]!.strength).toBe(10);
  });

  it('merges expansions without duplicating nodes or edges', () => {
    let state = graphReducer(emptyGraph, {
      type: 'start',
      center: artist('k'),
      page: page(['s']),
    });
    state = graphReducer(state, {
      type: 'expand',
      id: 's',
      page: page(['k', 'x']),
      append: false,
    });
    expect(Object.keys(state.nodes).sort()).toEqual(['k', 's', 'x']);
    expect(Object.keys(state.edges)).toHaveLength(2);
    expect(state.nodes['s']!.expanded).toBe(true);
  });

  it('appends "show more" pages to the count', () => {
    let state = graphReducer(emptyGraph, {
      type: 'start',
      center: artist('k'),
      page: page(['a'], 2, 't'),
    });
    state = graphReducer(state, {
      type: 'expand',
      id: 'k',
      page: page(['b'], 2),
      append: true,
    });
    expect(state.expansions['k']).toEqual({
      shown: 2,
      total: 2,
      nextPageToken: '',
    });
  });

  it('ignores expansions of unknown nodes', () => {
    const state = graphReducer(emptyGraph, {
      type: 'expand',
      id: 'nope',
      page: page(['a']),
      append: false,
    });
    expect(state).toBe(emptyGraph);
  });

  it('caps the visible nodes and counts what was left out', () => {
    const many = Array.from(
      {length: MAX_VISIBLE_NODES + 25},
      (_, i) => `n${i}`,
    );
    const state = graphReducer(emptyGraph, {
      type: 'start',
      center: artist('k'),
      page: page(many),
    });
    expect(Object.keys(state.nodes)).toHaveLength(MAX_VISIBLE_NODES);
    expect(state.capped).toBe(26);
  });

  it('lists neighbors strongest first', () => {
    const state = graphReducer(emptyGraph, {
      type: 'start',
      center: artist('k'),
      page: page(['a', 'b', 'c']),
    });
    expect(neighborsOf(state, 'k').map(n => n.node.id)).toEqual([
      'a',
      'b',
      'c',
    ]);
  });

  it('records the expansion trail and undoes one step at a time', () => {
    let state = graphReducer(emptyGraph, {
      type: 'start',
      center: artist('k'),
      page: page(['s', 't']),
    });
    const afterStart = state;
    state = graphReducer(state, {
      type: 'expand',
      id: 's',
      page: page(['x']),
      append: false,
    });
    state = graphReducer(state, {
      type: 'expand',
      id: 's',
      page: page(['y']),
      append: true,
    });
    expect(state.trail).toEqual(['k', 's']); // "show more" adds no breadcrumb
    expect(state.past).toHaveLength(2);
    state = graphReducer(state, {type: 'undo'});
    expect(Object.keys(state.nodes).sort()).toEqual(['k', 's', 't', 'x']);
    state = graphReducer(state, {type: 'undo'});
    expect({...state, past: []}).toEqual({...afterStart, past: []});
    expect(graphReducer(state, {type: 'undo'})).toBe(state);
  });

  it('bounds the undo history', () => {
    let state = graphReducer(emptyGraph, {
      type: 'start',
      center: artist('k'),
      page: page(['s']),
    });
    for (let i = 0; i < MAX_UNDO + 5; i++) {
      state = graphReducer(state, {
        type: 'expand',
        id: 's',
        page: page([`n${i}`]),
        append: true,
      });
    }
    expect(state.past).toHaveLength(MAX_UNDO);
  });

  it('picks the strongest neighbors not yet expanded', () => {
    let state = graphReducer(emptyGraph, {
      type: 'start',
      center: artist('k'),
      page: page(['s', 't', 'u']),
    });
    state = graphReducer(state, {
      type: 'expand',
      id: 's',
      page: page([]),
      append: false,
    });
    expect(strongestUnexpanded(state, 'k', 2)).toEqual(['t', 'u']);
  });

  it('carries artist photos, and fills one in when a later page has it', () => {
    const withPhoto = (id: string) => ({
      ...artist(id),
      imageUrl: `https://upload.wikimedia.org/${id}.jpg`,
    });
    let state = graphReducer(emptyGraph, {
      type: 'start',
      center: withPhoto('k'),
      page: page(['s']),
    });
    expect(state.nodes['k']!.image).toBe('https://upload.wikimedia.org/k.jpg');
    // Summaries stored before photos existed have no imageUrl at all.
    expect(state.nodes['s']!.image).toBeNull();
    state = graphReducer(state, {
      type: 'expand',
      id: 'k',
      page: {
        ...page([]),
        connections: [{...page(['s']).connections[0]!, artist: withPhoto('s')}],
      },
      append: true,
    });
    expect(state.nodes['s']!.image).toBe('https://upload.wikimedia.org/s.jpg');
    expect(photoOf({imageUrl: ''})).toBeNull();
    expect(photoOf({})).toBeNull();
  });
});

describe('what the web shows about people and songs', () => {
  it('keeps listener counts and fills them in from a later page', () => {
    let state = graphReducer(emptyGraph, {
      type: 'start',
      center: artist('k'),
      page: page(['s']),
    });
    expect(state.nodes['s']!.listeners).toBeNull();
    const later = page(['s']);
    later.connections[0]!.artist = {...artist('s'), listeners: 24_691};
    state = graphReducer(state, {
      type: 'expand',
      id: 'k',
      page: later,
      append: true,
    });
    expect(state.nodes['s']!.listeners).toBe(24_691);
  });

  it('reads listener counts loosely, like photos', () => {
    expect(listenersOf({listeners: 120})).toBe(120);
    expect(listenersOf({listeners: 0})).toBeNull();
    expect(listenersOf({listeners: '12'})).toBeNull();
    expect(listenersOf({})).toBeNull();
  });

  it('takes shared songs from highlights, recordings only, without repeats', () => {
    const subject = (name: string, displayName: string) => ({
      subject: {name, displayName},
    });
    expect(
      songsOf([
        subject('recordings/r1', 'All the Stars'),
        subject('recordings/r2', 'all the stars'),
        subject('releases/x', 'Black Panther: The Album'),
        subject('recordings/r3', 'Doves in the Wind'),
        {subject: null},
      ]),
    ).toEqual([
      {id: 'r1', title: 'All the Stars'},
      {id: 'r3', title: 'Doves in the Wind'},
    ]);
  });

  it('keeps known songs when the same connection arrives without any', () => {
    const first = page(['s']);
    first.connections[0]!.highlights = [
      {subject: {name: 'recordings/r1', displayName: 'Song'}},
    ] as never;
    let state = graphReducer(emptyGraph, {
      type: 'start',
      center: artist('k'),
      page: first,
    });
    state = graphReducer(state, {
      type: 'expand',
      id: 's',
      page: page(['k']),
      append: false,
    });
    expect(state.edges[edgeKey('k', 's')]!.songs).toEqual([
      {id: 'r1', title: 'Song'},
    ]);
  });

  it('puts a connection in one orbit: performing first, then production', () => {
    expect(orbitOf(['PRODUCED_FOR', 'PERFORMED_WITH'])).toBe('FEATURES');
    expect(orbitOf(['CO_PRODUCED'])).toBe('PRODUCTION');
    expect(orbitOf(['CONTRIBUTED_TO', 'ENGINEERED'])).toBe('CREDITS');
    expect(orbitOf(['MEMBER_OF'])).toBe('CREDITS');
  });
});
