import {describe, expect, it} from 'vitest';

import {beatSeconds, moodProfile} from '../songs/Descriptors';

import {
  countryName,
  duration,
  listenersOf,
  perYear,
  photoOf,
  spanOf,
  spanText,
  yearOf,
  youTubeMusicSearch,
} from './facts';
import {groupLinks} from './links';
import {explain, listOf, type Reason} from './reasons';
import {splitTop} from '../screens/GenreScreen';

describe('entity facts', () => {
  it('reads a photo only when it has a URL', () => {
    expect(photoOf({})).toBeNull();
    expect(photoOf({image: null})).toBeNull();
    expect(photoOf({image: {url: ''}})).toBeNull();
    expect(photoOf({image: {url: 'https://x/a.jpg', author: 'A'}})).toEqual({
      url: 'https://x/a.jpg',
      author: 'A',
    });
  });

  it('spans years, ignoring unknowns', () => {
    expect(spanOf([null, 2015, 2011, undefined, 2022])).toEqual({
      first: 2011,
      last: 2022,
    });
    expect(spanOf([null])).toBeNull();
    expect(spanText({first: 2012, last: 2012})).toBe('2012');
    expect(spanText({first: 2012, last: 2022})).toBe('2012–2022');
    expect(spanText(null)).toBeNull();
  });

  it('parses years and durations', () => {
    expect(yearOf('1987-06-17')).toBe(1987);
    expect(yearOf(null)).toBeNull();
    expect(duration(177_000)).toEqual({minutes: 2, seconds: '57'});
    expect(duration(0)).toBeNull();
  });

  it('counts per year with gaps filled', () => {
    expect(perYear([2012, 2014, 2012, null])).toEqual([
      {year: 2012, count: 2},
      {year: 2013, count: 0},
      {year: 2014, count: 1},
    ]);
  });

  it('builds a YouTube Music search link', () => {
    expect(youTubeMusicSearch(' HUMBLE. Kendrick Lamar ')).toBe(
      'https://music.youtube.com/search?q=HUMBLE.%20Kendrick%20Lamar',
    );
  });

  it('names countries', () => {
    expect(countryName('US', 'en-US')).toBe('United States');
    expect(countryName(null, 'en-US')).toBeNull();
  });
});

describe('artist links', () => {
  const links = [
    {linkType: 'discogs', url: 'https://www.discogs.com/artist/1'},
    {linkType: 'discogs', url: 'https://www.discogs.com/artist/2'},
    {linkType: 'free streaming', url: 'https://open.spotify.com/artist/x'},
    {linkType: 'streaming', url: 'https://music.apple.com/us/artist/1'},
    {linkType: 'official homepage', url: 'http://www.kendricklamar.com/'},
    {linkType: 'youtube', url: 'https://www.youtube.com/channel/a'},
    {linkType: 'youtube', url: 'https://www.youtube.com/channel/b'},
    {linkType: 'social network', url: 'https://www.instagram.com/k'},
    {linkType: 'other', url: 'javascript:alert(1)'},
  ];
  const sources = [
    // A Discogs ID on a MusicBrainz URL: a broken link, dropped.
    {source: 'discogs', url: 'https://musicbrainz.org/artist/1539549'},
    {source: 'musicbrainz', url: 'https://musicbrainz.org/artist/abc'},
  ];

  it('groups, names and deduplicates', () => {
    const groups = Object.fromEntries(
      groupLinks(links, sources).map(([group, list]) => [
        group,
        list.map(l => l.name),
      ]),
    );
    expect(groups).toEqual({
      listen: ['YouTube', 'Spotify', 'Apple Music'],
      official: ['kendricklamar.com'],
      social: ['Instagram'],
      reference: ['MusicBrainz', 'Discogs'],
    });
  });

  it('keeps the matching source link', () => {
    const reference = groupLinks([], sources)[0]![1];
    expect(reference).toEqual([
      {
        url: 'https://musicbrainz.org/artist/abc',
        name: 'MusicBrainz',
        group: 'reference',
      },
    ]);
  });
});

describe('sound profile', () => {
  it('marks the two strongest moods at 50% or more', () => {
    const profile = moodProfile({
      danceable: 0.9,
      sad: 0.2,
      party: 0.6,
      happy: 0.55,
    });
    expect(profile.filter(p => p.strong).map(p => p.mood)).toEqual([
      'danceable',
      'party',
    ]);
    expect(profile.map(p => p.mood)).toEqual([
      'danceable',
      'happy',
      'sad',
      'party',
    ]);
  });

  it('turns a tempo into a beat', () => {
    expect(beatSeconds(120)).toBe(0.5);
    expect(beatSeconds(null)).toBeNull();
    expect(beatSeconds(900)).toBeNull();
  });
});

describe('listeners', () => {
  it('reads a positive count only', () => {
    expect(listenersOf({listeners: 25_300})).toBe(25_300);
    expect(listenersOf({listeners: null})).toBeNull();
    expect(listenersOf({listeners: 0})).toBeNull();
    expect(listenersOf({})).toBeNull();
  });
});

describe('recommendation reasons', () => {
  const person = (displayName: string) => ({
    name: `artists/${displayName}`,
    displayName,
    disambiguation: null,
    artistType: null,
    country: null,
    genreKnown: true,
    imageUrl: null,
    listeners: null,
  });
  const reason = (r: Partial<Reason> & Pick<Reason, 'kind'>): Reason => ({
    messageId: '',
    params: {},
    via: [],
    label: null,
    source: null,
    ...r,
  });

  it('orders collaborators, then listeners, then label', () => {
    const lines = explain([
      reason({
        kind: 'SAME_LABEL',
        label: {name: 'labels/i', displayName: 'Interscope Records'},
      }),
      reason({
        kind: 'LISTENERS_IN_COMMON',
        params: {rank: 6, strength: 'STRONG'},
      }),
      reason({
        kind: 'SHARED_COLLABORATORS',
        params: {count: 19},
        via: ['Lil Wayne', 'JAŸ-Z', 'Snoop Dogg', 'Drake'].map(person),
      }),
    ]);
    expect(lines.map(l => [l.messageId, l.values])).toEqual([
      ['recommend.shared', {count: 19}],
      ['recommend.listeners.strong', {}],
      ['recommend.label', {label: 'Interscope Records'}],
    ]);
    expect(lines[0]!.via.map(v => v.displayName)).toEqual([
      'Lil Wayne',
      'JAŸ-Z',
      'Snoop Dogg',
    ]);
  });

  it('words moderate overlap plainly and drops reasons it cannot back', () => {
    const lines = explain([
      reason({kind: 'LISTENERS_IN_COMMON', params: {strength: 'MODERATE'}}),
      reason({kind: 'SAME_LABEL'}),
      reason({kind: 'SHARED_COLLABORATORS', params: {count: 0}}),
    ]);
    expect(lines.map(l => l.messageId)).toEqual(['recommend.listeners']);
  });

  it('falls back to the via count and the label param', () => {
    const lines = explain([
      reason({kind: 'SHARED_COLLABORATORS', via: [person('A'), person('B')]}),
      reason({kind: 'SAME_LABEL', params: {label: 'TDE'}}),
    ]);
    expect(lines.map(l => l.values)).toEqual([{count: 2}, {label: 'TDE'}]);
  });

  it('lists names in the interface language', () => {
    expect(listOf(['A', 'B', 'C'], 'en-US')).toBe('A, B, and C');
    expect(listOf(['A'], 'en-US')).toBe('A');
  });
});

describe('genre page', () => {
  it('puts the first ten on the shelf and ranks the rest', () => {
    const items = Array.from({length: 13}, (_, i) => i);
    expect(splitTop(items)).toEqual({
      top: [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
      rest: [10, 11, 12],
    });
    expect(splitTop([1, 2])).toEqual({top: [1, 2], rest: []});
  });
});
