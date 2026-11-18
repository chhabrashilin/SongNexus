/**
 * Small, pure derivations for the entity pages (artist, song, label): photos,
 * year spans, durations and grouping. Everything here is computed from data
 * the API already returns; nothing is guessed.
 */

/** A freely licensed photo of an artist (Wikimedia Commons, ADR 0009). */
export interface Photo {
  url: string;
  thumbnailUrl?: string | null;
  width?: number | null;
  height?: number | null;
  /** The file page on Wikimedia Commons. */
  pageUrl?: string | null;
  author?: string | null;
  license?: string | null;
  licenseUrl?: string | null;
}

/**
 * The photo on an artist detail, read defensively so it type-checks before
 * and after the API schema carries `image`.
 */
export function photoOf(detail: object | null | undefined): Photo | null {
  const image = (detail as {image?: Partial<Photo> | null} | null)?.image;
  return image && typeof image.url === 'string' && image.url
    ? (image as Photo)
    : null;
}

/**
 * Public ListenBrainz listener count on an artist, read defensively so it
 * type-checks before and after the API schema carries `listeners`.
 */
export function listenersOf(artist: object | null | undefined): number | null {
  const value = (artist as {listeners?: unknown} | null)?.listeners;
  return typeof value === 'number' && Number.isFinite(value) && value > 0
    ? value
    : null;
}

export interface Span {
  first: number;
  last: number;
}

/** The first and last of some years, ignoring unknowns; null when none are known. */
export function spanOf(
  years: Iterable<number | null | undefined>,
): Span | null {
  let first = Infinity;
  let last = -Infinity;
  for (const year of years) {
    if (typeof year !== 'number' || !Number.isFinite(year)) continue;
    first = Math.min(first, year);
    last = Math.max(last, year);
  }
  return first === Infinity ? null : {first, last};
}

/** "2012" or "2012–2022". */
export function spanText(span: Span | null): string | null {
  if (!span) return null;
  return span.first === span.last
    ? String(span.first)
    : `${span.first}–${span.last}`;
}

/** The year of an ISO date ("1987-06-17" → 1987), or null. */
export function yearOf(date: string | null | undefined): number | null {
  const match = /^(\d{4})/.exec(date ?? '');
  return match ? Number(match[1]) : null;
}

/** Minutes and zero-padded seconds from milliseconds, or null. */
export function duration(
  ms: number | null | undefined,
): {minutes: number; seconds: string} | null {
  if (!ms || ms <= 0) return null;
  const total = Math.round(ms / 1000);
  return {
    minutes: Math.floor(total / 60),
    seconds: String(total % 60).padStart(2, '0'),
  };
}

/** Groups items by a key, keeping first-seen order of keys and items. */
export function groupBy<T, K>(items: T[], key: (item: T) => K): [K, T[]][] {
  const groups = new Map<K, T[]>();
  for (const item of items) {
    const k = key(item);
    const list = groups.get(k);
    if (list) list.push(item);
    else groups.set(k, [item]);
  }
  return [...groups.entries()];
}

/** Counts per year, gaps filled with zero, so a column chart keeps honest time. */
export function perYear(
  years: (number | null)[],
): {year: number; count: number}[] {
  const span = spanOf(years);
  if (!span) return [];
  const counts = new Map<number, number>();
  for (const year of years) {
    if (year !== null) counts.set(year, (counts.get(year) ?? 0) + 1);
  }
  const out: {year: number; count: number}[] = [];
  for (let year = span.first; year <= span.last; year++) {
    out.push({year, count: counts.get(year) ?? 0});
  }
  return out;
}

/** A country's name in the interface language ("US" → "United States"). */
export function countryName(
  code: string | null | undefined,
  locale: string,
): string | null {
  if (!code) return null;
  try {
    return (
      new Intl.DisplayNames([locale === 'ar-XB' ? 'ar' : 'en'], {
        type: 'region',
      }).of(code) ?? code
    );
  } catch {
    return code;
  }
}

/** The YouTube Music search for a subject. We never claim playback we don't have. */
export function youTubeMusicSearch(query: string): string {
  return `https://music.youtube.com/search?q=${encodeURIComponent(query.trim())}`;
}
