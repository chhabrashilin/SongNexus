/** Pure helpers for Around you: ranges, progress, places, overlap and share links. */

export interface Range {
  min: number;
  max?: number | null;
}

/** How a listener range reads: "3–4 listeners" or "10,000+ listeners". */
export function rangeParts(range: Range): {
  kind: 'between' | 'atLeast';
  min: number;
  max: number;
} {
  return range.max === null || range.max === undefined
    ? {kind: 'atLeast', min: range.min, max: range.min}
    : {kind: 'between', min: range.min, max: range.max};
}

/** Listeners so far toward unlocking a chart, as a 0–1 fraction (never negative). */
export function unlockProgress(needed: number, minimum: number): number {
  if (minimum <= 0) return 1;
  const have = Math.max(0, minimum - Math.max(0, needed));
  return Math.min(1, have / minimum);
}

/** "Madison, WI" in the US (the state code), "Toronto, CA" elsewhere. */
export function placeLabel(place: {
  city: string;
  region: string;
  country: string;
}): string {
  const area =
    place.country === 'US' && place.region.startsWith('US-')
      ? place.region.slice(3)
      : place.country;
  return [place.city, area].filter(Boolean).join(', ');
}

export interface Ranked {
  rank: number;
  artist: {name: string; displayName: string};
}

export interface SharedArtist {
  name: string;
  displayName: string;
  rankA: number;
  rankB: number;
}

/** Artists on both charts, best combined rank first (ties: alphabetical). */
export function overlap(
  a: readonly Ranked[],
  b: readonly Ranked[],
): SharedArtist[] {
  const other = new Map(b.map(row => [row.artist.name, row.rank]));
  const shared: SharedArtist[] = [];
  for (const row of a) {
    const rankB = other.get(row.artist.name);
    if (rankB !== undefined)
      shared.push({
        name: row.artist.name,
        displayName: row.artist.displayName,
        rankA: row.rank,
        rankB,
      });
  }
  return shared.sort(
    (x, y) =>
      x.rankA + x.rankB - (y.rankA + y.rankB) ||
      x.displayName.localeCompare(y.displayName),
  );
}

/** Share of the smaller chart's artists that both charts have (0–1). */
export function overlapShare(
  shared: number,
  a: readonly unknown[],
  b: readonly unknown[],
): number {
  const smaller = Math.min(a.length, b.length);
  return smaller === 0 ? 0 : shared / smaller;
}

/** The Around you link that opens a community directly (shareable). */
export function shareUrl(origin: string, communityName: string): string {
  const id = communityName.slice(communityName.lastIndexOf('/') + 1);
  return `${origin.replace(/\/$/, '')}/around-you?c=${encodeURIComponent(id)}`;
}

/** Keeps a community slug safe to put in a request path (slugs are lowercase words). */
export function cleanSlug(
  value: string | null | undefined,
): string | undefined {
  if (!value) return undefined;
  return /^[a-z0-9][a-z0-9-]{0,127}$/.test(value) ? value : undefined;
}
