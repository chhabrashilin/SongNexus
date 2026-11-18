/** Pure helpers for story cards: template values, links and the artist lookup. */
import {idOf, type Schemas} from '../api/client';

export type Story = Schemas['Story'];

/** Template values for the story sentence: artist names by role, plus its other parameters. */
export function storyValues(story: Story): Record<string, string | number> {
  const values: Record<string, string | number> = {...story.params};
  for (const part of story.parts) values[part.role] = part.artist.displayName;
  return values;
}

/** Resolves `artists/{id}` to a display name for the evidence list. */
export function artistNamer(story: Story): (name: string) => string {
  const names = new Map(
    story.parts.map(p => [p.artist.name, p.artist.displayName]),
  );
  return name => names.get(name) ?? '';
}

function part(story: Story, role: string) {
  return story.parts.find(p => p.role === role)?.artist;
}

/** The pair to open in the path finder: the lead artist and the other end. */
export function pathPair(story: Story): [string, string] | null {
  const from = part(story, 'a');
  const to = part(story, 'b') ?? part(story, 'via');
  return from && to ? [idOf(from.name), idOf(to.name)] : null;
}

export function pathLink(story: Story): string | null {
  const pair = pathPair(story);
  return pair ? `/six-degrees?from=${pair[0]}&to=${pair[1]}` : null;
}

/** The artist whose connection web opens from the story. */
export function webLink(story: Story): string | null {
  const lead = part(story, 'a') ?? story.parts[0]?.artist;
  return lead ? `/explore/${idOf(lead.name)}` : null;
}

/** What to share with a friend: a path between two artists, or the lead artist. */
export function shareSubjects(story: Story): {
  kind: 'PATH' | 'ARTIST';
  subjects: string[];
} {
  const pair = pathPair(story);
  const a = part(story, 'a');
  return pair && a
    ? {kind: 'PATH', subjects: pair}
    : {kind: 'ARTIST', subjects: a ? [idOf(a.name)] : []};
}

type Step = -1 | 0 | 1;
type Dir = 'ltr' | 'rtl';

/**
 * The step between stories for a key, or 0 when the key is not a navigation
 * key. Down and "forward" (right in left-to-right scripts, left in
 * right-to-left ones) go to the next story.
 */
export function stepForKey(key: string, dir: Dir = 'ltr'): Step {
  const forward = dir === 'rtl' ? 'ArrowLeft' : 'ArrowRight';
  const backward = dir === 'rtl' ? 'ArrowRight' : 'ArrowLeft';
  if (key === 'ArrowDown' || key === 'PageDown' || key === forward) return 1;
  if (key === 'ArrowUp' || key === 'PageUp' || key === backward) return -1;
  return 0;
}

export function clampIndex(index: number, count: number): number {
  return Math.max(0, Math.min(count - 1, index));
}

/** The story's ID for links (`stories/{id}` → `{id}`). */
export function storyId(story: Pick<Story, 'name'>): string {
  return story.name.slice(story.name.indexOf('/') + 1);
}

/**
 * Where `?story=` points in the loaded stories: a story ID, or a 1-based
 * position for older links. -1 when it is not (yet) loaded.
 */
export function findStory(
  stories: Pick<Story, 'name'>[],
  param: string | null,
): number {
  if (!param) return -1;
  const byId = stories.findIndex(s => storyId(s) === param);
  if (byId !== -1) return byId;
  if (/^\d{1,4}$/.test(param)) {
    const n = Number(param) - 1;
    return n >= 0 && n < stories.length ? n : -1;
  }
  return -1;
}

/** A story's deep link. */
export function storyLink(origin: string, story: Pick<Story, 'name'>): string {
  return new URL(`/stories?story=${encodeURIComponent(storyId(story))}`, origin)
    .href;
}

/**
 * The people in a story in the order they are drawn: the lead, the person
 * between them, the other end. A story about two people draws two.
 */
export function orderedParts(story: Story): Story['parts'] {
  const rank = (role: string) => (role === 'a' ? 0 : role === 'via' ? 1 : 2);
  return [...story.parts].sort((x, y) => rank(x.role) - rank(y.role));
}

/** A horizontal swipe of at least `min` pixels steps; a mostly vertical one scrolls. */
export function swipeStep(
  dx: number,
  dy: number,
  dir: Dir = 'ltr',
  min = 48,
): Step {
  if (Math.abs(dx) < min || Math.abs(dx) < Math.abs(dy) * 1.5) return 0;
  const toNext = dir === 'rtl' ? dx > 0 : dx < 0;
  return toNext ? 1 : -1;
}

/** Tap zones: the first third goes back, the last third forward, the middle does nothing. */
export function tapStep(x: number, width: number, dir: Dir = 'ltr'): Step {
  if (width <= 0) return 0;
  const third = width / 3;
  const zone: Step = x < third ? -1 : x > width - third ? 1 : 0;
  return dir === 'rtl' ? ((-zone || 0) as Step) : zone;
}
