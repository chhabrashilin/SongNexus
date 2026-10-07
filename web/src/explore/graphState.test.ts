import {describe, expect, it} from 'vitest';

import type {Schemas} from '../api/client';

import {
  MAX_VISIBLE_NODES,
  edgeKey,
  emptyGraph,
  graphReducer,
  neighborsOf,
} from './graphState';

const artist = (id: string) => ({
  name: `artists/${id}`,
  displayName: id.toUpperCase(),
  disambiguation: null,
  artistType: null,
  country: null,
  genreKnown: id < 'm',
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
});
