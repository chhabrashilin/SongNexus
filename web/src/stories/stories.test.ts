import {describe, expect, it} from 'vitest';

import {
  artistNamer,
  clampIndex,
  pathLink,
  shareSubjects,
  stepForKey,
  storyValues,
  webLink,
  type Story,
} from './stories';

const artist = (id: string, displayName: string) => ({
  name: `artists/${id}`,
  displayName,
  artistType: null,
  country: null,
  disambiguation: null,
  genreKnown: true,
});

const story = (parts: Story['parts']): Story =>
  ({
    name: 'stories/x',
    kind: 'SHARED_PRODUCER',
    messageId: 'story.sharedProducer',
    parts,
    params: {n: 3},
    credits: [],
  }) as Story;

const pair = story([
  {role: 'a', artist: artist('1', 'Alpha')},
  {role: 'b', artist: artist('2', 'Beta')},
  {role: 'via', artist: artist('3', 'Gamma')},
]);
const solo = story([
  {role: 'a', artist: artist('1', 'Alpha')},
  {role: 'via', artist: artist('3', 'Gamma')},
]);

describe('story helpers', () => {
  it('builds template values from roles and params', () => {
    expect(storyValues(pair)).toEqual({
      n: 3,
      a: 'Alpha',
      b: 'Beta',
      via: 'Gamma',
    });
    expect(artistNamer(pair)('artists/2')).toBe('Beta');
  });

  it('links to the web and the path finder', () => {
    expect(webLink(pair)).toBe('/explore/1');
    expect(pathLink(pair)).toBe('/six-degrees?from=1&to=2');
    expect(pathLink(solo)).toBe('/six-degrees?from=1&to=3');
    expect(shareSubjects(pair)).toEqual({kind: 'PATH', subjects: ['1', '2']});
  });

  it('maps navigation keys and clamps', () => {
    expect(stepForKey('ArrowDown')).toBe(1);
    expect(stepForKey('PageUp')).toBe(-1);
    expect(stepForKey('a')).toBe(0);
    expect(clampIndex(-1, 4)).toBe(0);
    expect(clampIndex(9, 4)).toBe(3);
  });
});
