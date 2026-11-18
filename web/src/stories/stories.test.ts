import {describe, expect, it} from 'vitest';

import {
  artistNamer,
  clampIndex,
  findStory,
  orderedParts,
  pathLink,
  shareSubjects,
  stepForKey,
  storyId,
  storyLink,
  storyValues,
  swipeStep,
  tapStep,
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
  imageUrl: null,
  listeners: null,
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

  it('maps sideways keys by reading direction', () => {
    expect(stepForKey('ArrowRight')).toBe(1);
    expect(stepForKey('ArrowLeft')).toBe(-1);
    expect(stepForKey('ArrowRight', 'rtl')).toBe(-1);
    expect(stepForKey('ArrowLeft', 'rtl')).toBe(1);
    expect(stepForKey('PageDown', 'rtl')).toBe(1);
  });

  it('finds a deep-linked story by ID or position', () => {
    const list = [{name: 'stories/aa'}, {name: 'stories/bb'}];
    expect(storyId(list[1]!)).toBe('bb');
    expect(findStory(list, 'bb')).toBe(1);
    expect(findStory(list, '1')).toBe(0);
    expect(findStory(list, '3')).toBe(-1);
    expect(findStory(list, '0')).toBe(-1);
    expect(findStory(list, 'zz')).toBe(-1);
    expect(findStory(list, null)).toBe(-1);
    expect(storyLink('https://x.test', list[0]!)).toBe(
      'https://x.test/stories?story=aa',
    );
  });

  it('draws the lead, the person between, then the other end', () => {
    expect(orderedParts(pair).map(p => p.role)).toEqual(['a', 'via', 'b']);
    expect(orderedParts(solo).map(p => p.role)).toEqual(['a', 'via']);
  });

  it('steps on a sideways swipe, not on a scroll', () => {
    expect(swipeStep(-80, 10)).toBe(1);
    expect(swipeStep(80, 10)).toBe(-1);
    expect(swipeStep(80, 10, 'rtl')).toBe(1);
    expect(swipeStep(-30, 0)).toBe(0);
    expect(swipeStep(-80, 70)).toBe(0);
  });

  it('maps tap zones by thirds', () => {
    expect(tapStep(10, 300)).toBe(-1);
    expect(tapStep(150, 300)).toBe(0);
    expect(tapStep(290, 300)).toBe(1);
    expect(tapStep(10, 300, 'rtl')).toBe(1);
    expect(tapStep(150, 300, 'rtl')).toBe(0);
    expect(tapStep(10, 0)).toBe(0);
  });
});
