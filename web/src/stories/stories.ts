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

/** The step between story cards for a key, or 0 when the key is not a navigation key. */
export function stepForKey(key: string): -1 | 0 | 1 {
  if (key === 'ArrowDown' || key === 'PageDown') return 1;
  if (key === 'ArrowUp' || key === 'PageUp') return -1;
  return 0;
}

export function clampIndex(index: number, count: number): number {
  return Math.max(0, Math.min(count - 1, index));
}
