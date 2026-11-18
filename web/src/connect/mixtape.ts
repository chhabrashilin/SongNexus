/**
 * The pure parts of the exploring tools (find a path, compare): turning a path
 * into a mixtape and a shareable track list, picking a surprise pair, and the
 * proportions the head-to-head meters draw. No React, so all of it is
 * unit-tested.
 */
import type {ArtistSummary, Evidence, Schemas} from '../api/client';
import {idOf} from '../api/client';
import {
  CATEGORY_ENCODING,
  dominantCategory,
  type Category,
} from '../components/encoding';

export type PathStep = Schemas['PathStep'];
export type PathTrack = Schemas['PathTrack'];

/** One row of the mixtape: the step it stands for and its song, if any. */
export interface MixtapeRow {
  /** 1-based step number. */
  step: number;
  from: ArtistSummary;
  to: ArtistSummary;
  /** Null when only a relation (such as band membership) links the two. */
  track: PathTrack | null;
}

/** The path as a track list, in path order. */
export function mixtapeOf(steps: readonly PathStep[]): MixtapeRow[] {
  return steps.map((step, index) => ({
    step: index + 1,
    from: step.fromArtist,
    to: step.toArtist,
    track: step.track ?? null,
  }));
}

/** The songs in a mixtape (rows without one are skipped). */
export function tracksOf(rows: readonly MixtapeRow[]): PathTrack[] {
  return rows.flatMap(row => (row.track ? [row.track] : []));
}

/** The year span of the songs ("2006–2022"), or null when no year is known. */
export function yearSpan(
  tracks: readonly PathTrack[],
): {first: number; last: number} | null {
  const years = tracks
    .map(track => track.year)
    .filter((year): year is number => typeof year === 'number');
  if (years.length === 0) return null;
  return {first: Math.min(...years), last: Math.max(...years)};
}

/** The in-app song page for a track. */
export function songPath(track: Pick<PathTrack, 'recording'>): string {
  return `/song/${idOf(track.recording)}`;
}

/** What to search for on YouTube Music to find this track. */
export function trackQuery(track: Pick<PathTrack, 'displayName' | 'artists'>) {
  const artist = track.artists[0]?.displayName;
  return artist ? `${track.displayName} ${artist}` : track.displayName;
}

/** A search on YouTube Music: we link out, we never claim playback. */
export function youTubeMusicUrl(query: string): string {
  return `https://music.youtube.com/search?q=${encodeURIComponent(query.trim())}`;
}

export interface MixtapeWords {
  /** The first line ("Kendrick Lamar to Daft Punk: …"). */
  title: string;
  /** One line per song. */
  line: (n: number, track: PathTrack) => string;
  /** Where the path lives, appended last. */
  url?: string;
}

/**
 * The mixtape as plain text, to copy or share: a title, one numbered line per
 * song (rows without a song are left out, numbering stays continuous), and the
 * link to the path.
 */
export function mixtapeText(
  rows: readonly MixtapeRow[],
  words: MixtapeWords,
): string {
  const lines = tracksOf(rows).map((track, index) =>
    words.line(index + 1, track),
  );
  return [
    words.title,
    '',
    ...lines,
    ...(words.url ? ['', words.url] : []),
  ].join('\n');
}

/** The kind of connection a step mostly is, from its credits. */
export function stepCategory(evidence: readonly Evidence[]): Category {
  return dominantCategory(evidence.map(e => e.kind));
}

/**
 * Two different artists picked at random from `ids`, avoiding the pair on
 * screen now (in either order) when there is any other choice. Null when there
 * are fewer than two to choose from.
 */
export function surprisePair(
  ids: readonly string[],
  current: readonly [string | null, string | null] = [null, null],
  random: () => number = Math.random,
): [string, string] | null {
  const unique = [...new Set(ids)];
  if (unique.length < 2) return null;
  const same = (a: string, b: string) =>
    (a === current[0] && b === current[1]) ||
    (a === current[1] && b === current[0]);
  for (let attempt = 0; attempt < 12; attempt++) {
    const i = Math.floor(random() * unique.length) % unique.length;
    let j = Math.floor(random() * (unique.length - 1)) % (unique.length - 1);
    if (j >= i) j++;
    const pair: [string, string] = [unique[i]!, unique[j]!];
    if (!same(...pair) || unique.length === 2) return pair;
  }
  // Unlucky draws: take the first pair that differs from the current one.
  for (const a of unique)
    for (const b of unique) if (a !== b && !same(a, b)) return [a, b];
  return [unique[0]!, unique[1]!];
}

/**
 * The two sides of a comparison in the data colors (validated palette, see
 * `components/encoding.ts`): side A takes the first series, side B the second.
 */
export const SIDE_COLOR = {
  a: CATEGORY_ENCODING.FEATURES.color,
  b: CATEGORY_ENCODING.PRODUCERS.color,
} as const;

/** Strength of a shared audience as a level from 0 (none) to 3 (strong). */
export const AUDIENCE_LEVELS = ['NONE', 'WEAK', 'MODERATE', 'STRONG'] as const;
export type AudienceStrength = (typeof AUDIENCE_LEVELS)[number];

export function audienceLevel(strength: AudienceStrength): number {
  return Math.max(0, AUDIENCE_LEVELS.indexOf(strength));
}

/** Two counts as shares of the larger one (0–1), for paired bars. */
export function pairShares(a: number, b: number): [number, number] {
  const top = Math.max(a, b);
  if (top <= 0) return [0, 0];
  return [a / top, b / top];
}

/** Per-kind credit counts for both sides, in a stable order, for "each on their own". */
export const COUNT_KINDS = ['FEATURE', 'PRODUCTION', 'BAND', 'CREDIT'] as const;
export type CountKind = (typeof COUNT_KINDS)[number];

export function countRows(
  a: Record<string, number>,
  b: Record<string, number>,
): {kind: CountKind; a: number; b: number}[] {
  return COUNT_KINDS.map(kind => ({
    kind,
    a: a[kind] ?? 0,
    b: b[kind] ?? 0,
  })).filter(row => row.a > 0 || row.b > 0);
}

/** The one-number readings (how alike two songs sound) take the third data color. */
export const MAGNITUDE_COLOR = CATEGORY_ENCODING.CONTRIBUTIONS.color;
