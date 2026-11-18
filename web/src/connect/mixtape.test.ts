import {describe, expect, it} from 'vitest';

import type {ArtistSummary, Evidence} from '../api/client';

import {
  audienceLevel,
  countRows,
  mixtapeOf,
  mixtapeText,
  pairShares,
  songPath,
  stepCategory,
  surprisePair,
  trackQuery,
  tracksOf,
  yearSpan,
  youTubeMusicUrl,
  type PathStep,
  type PathTrack,
} from './mixtape';

const artist = (name: string): ArtistSummary => ({
  name: `artists/${name.toLowerCase()}`,
  displayName: name,
  disambiguation: null,
  artistType: null,
  country: null,
  genreKnown: true,
  imageUrl: null,
  listeners: null,
});

const track = (title: string, by: string, year: number | null): PathTrack => ({
  recording: `recordings/${title.toLowerCase().replace(/\W/g, '')}`,
  displayName: title,
  artists: [artist(by)],
  firstReleaseDate: null,
  release: null,
  year,
});

const evidence = (kind: Evidence['kind']): Evidence => ({
  fromArtist: 'artists/a',
  toArtist: 'artists/b',
  fromRole: 'primary',
  toRole: 'featured',
  kind,
  messageId: 'evidence.featured',
  sources: [],
  subject: {name: 'recordings/x', displayName: 'X'} as Evidence['subject'],
});

const steps: PathStep[] = [
  {
    fromArtist: artist('Radiohead'),
    toArtist: artist('Jay-Z'),
    strength: 1,
    evidence: [evidence('PERFORMED_WITH')],
    track: track('99 Anthems', 'Jay-Z', 2009),
  },
  {
    fromArtist: artist('Jay-Z'),
    toArtist: artist('Beyonce'),
    strength: 2,
    evidence: [evidence('MEMBER_OF')],
    track: null,
  },
  {
    fromArtist: artist('Beyonce'),
    toArtist: artist('BTS'),
    strength: 4,
    evidence: [evidence('PRODUCED_FOR'), evidence('PERFORMED_WITH')],
    track: track('Bad decisions', 'BTS', 2022),
  },
];

describe('mixtape', () => {
  it('keeps every step in order, with or without a song', () => {
    const rows = mixtapeOf(steps);
    expect(rows.map(r => r.step)).toEqual([1, 2, 3]);
    expect(rows[1]!.track).toBeNull();
    expect(rows[2]!.from.displayName).toBe('Beyonce');
    expect(tracksOf(rows).map(t => t.displayName)).toEqual([
      '99 Anthems',
      'Bad decisions',
    ]);
  });

  it('spans the known years', () => {
    expect(yearSpan(tracksOf(mixtapeOf(steps)))).toEqual({
      first: 2009,
      last: 2022,
    });
    expect(yearSpan([track('A', 'B', null)])).toBeNull();
    expect(yearSpan([])).toBeNull();
  });

  it('writes a track list with continuous numbering and the link', () => {
    const text = mixtapeText(mixtapeOf(steps), {
      title: 'Radiohead to BTS',
      line: (n, t) => `${n}. ${t.displayName}`,
      url: 'https://example.test/p',
    });
    expect(text).toBe(
      'Radiohead to BTS\n\n1. 99 Anthems\n2. Bad decisions\n\nhttps://example.test/p',
    );
    expect(mixtapeText([], {title: 'T', line: () => 'never'})).toBe('T\n');
  });

  it('links to the song page and a YouTube Music search', () => {
    const song = track('HUMBLE.', 'Kendrick Lamar', 2017);
    expect(songPath(song)).toBe('/song/humble');
    expect(trackQuery(song)).toBe('HUMBLE. Kendrick Lamar');
    expect(trackQuery({...song, artists: []})).toBe('HUMBLE.');
    expect(youTubeMusicUrl(' a & b ')).toBe(
      'https://music.youtube.com/search?q=a%20%26%20b',
    );
  });

  it('names a step by its strongest kind of credit', () => {
    expect(stepCategory(steps[2]!.evidence)).toBe('FEATURES');
    expect(stepCategory(steps[1]!.evidence)).toBe('BANDS');
  });
});

describe('surprisePair', () => {
  it('needs two different artists', () => {
    expect(surprisePair([])).toBeNull();
    expect(surprisePair(['a', 'a'])).toBeNull();
  });

  it('always returns two different artists from the list', () => {
    let seed = 0;
    const random = () => (seed = (seed * 9301 + 49297) % 233280) / 233280;
    for (let i = 0; i < 200; i++) {
      const pair = surprisePair(['a', 'b', 'c', 'd'], [null, null], random)!;
      expect(pair[0]).not.toBe(pair[1]);
      expect(['a', 'b', 'c', 'd']).toEqual(expect.arrayContaining(pair));
    }
  });

  it('avoids the pair on screen, in either order', () => {
    // A generator stuck on the current pair still yields something new.
    const stuck = () => 0;
    const pair = surprisePair(['a', 'b', 'c'], ['b', 'a'], stuck)!;
    expect(new Set(pair)).not.toEqual(new Set(['a', 'b']));
    // With only two artists, the same pair is the only choice.
    expect(new Set(surprisePair(['a', 'b'], ['a', 'b'], stuck)!)).toEqual(
      new Set(['a', 'b']),
    );
  });
});

describe('head-to-head numbers', () => {
  it('scales two counts against the larger', () => {
    expect(pairShares(50, 200)).toEqual([0.25, 1]);
    expect(pairShares(0, 0)).toEqual([0, 0]);
  });

  it('orders audience strengths', () => {
    expect(audienceLevel('NONE')).toBe(0);
    expect(audienceLevel('STRONG')).toBe(3);
  });

  it('lists the kinds either side has, in a fixed order', () => {
    expect(countRows({CREDIT: 3, FEATURE: 1}, {BAND: 2, FEATURE: 4})).toEqual([
      {kind: 'FEATURE', a: 1, b: 4},
      {kind: 'BAND', a: 0, b: 2},
      {kind: 'CREDIT', a: 3, b: 0},
    ]);
  });
});
