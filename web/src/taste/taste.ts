/**
 * Pure helpers for "Your Nexus": turning a taste profile's shares into whole
 * percentages that add up, the genre mix's slices (four named hues and "other",
 * the only data colors we have), the decade spread with gaps filled, and the
 * text a listener copies to share it.
 */

/** Shares (0–1) as whole percentages that sum to 100 (largest remainder). */
export function wholePercents(shares: readonly number[]): number[] {
  const total = shares.reduce((sum, s) => sum + Math.max(0, s), 0);
  if (total <= 0) return shares.map(() => 0);
  const exact = shares.map(s => (Math.max(0, s) / total) * 100);
  const floors = exact.map(Math.floor);
  let left = 100 - floors.reduce((sum, n) => sum + n, 0);
  const order = exact
    .map((value, index) => ({index, rest: value - Math.floor(value)}))
    .sort((a, b) => b.rest - a.rest || a.index - b.index);
  for (const {index} of order) {
    if (left <= 0) break;
    floors[index]! += 1;
    left -= 1;
  }
  return floors;
}

/** The data colors, in order (components/encoding.ts); the last is "other". */
export const SLICE_COLORS = [
  'var(--series-1)',
  'var(--series-2)',
  'var(--series-3)',
  'var(--neutral-strong)',
  'var(--neutral-soft)',
] as const;

export interface Slice {
  key: string;
  /** A genre's name, or null for "everything else". */
  label: string | null;
  percent: number;
  color: string;
  /** Dash-free fills can't be told apart by color alone: a pattern index. */
  pattern: number;
}

/**
 * The genre mix as at most five slices: the four largest genres, then the rest
 * together. Slices that round to 0% are dropped.
 */
export function genreSlices(
  genres: readonly {genre: string; displayName: string; share: number}[],
  named = 4,
): Slice[] {
  const head = genres.slice(0, named);
  const rest = genres.slice(named).reduce((sum, g) => sum + g.share, 0);
  const shares = [...head.map(g => g.share), ...(rest > 0 ? [rest] : [])];
  const percents = wholePercents(shares);
  const slices: Slice[] = head.map((g, i) => ({
    key: g.genre,
    label: g.displayName,
    percent: percents[i]!,
    color: SLICE_COLORS[i]!,
    pattern: i,
  }));
  if (rest > 0)
    slices.push({
      key: 'other',
      label: null,
      percent: percents[head.length]!,
      color: SLICE_COLORS[4],
      pattern: 4,
    });
  return slices.filter(s => s.percent > 0);
}

export interface DecadeBar {
  decade: number;
  percent: number;
  /** Height relative to the busiest decade (0–1). */
  height: number;
  peak: boolean;
}

/** Every decade from the first to the last (gaps as 0), with the peak marked. */
export function decadeBars(
  decades: readonly {decade: number; share: number}[],
): DecadeBar[] {
  if (decades.length === 0) return [];
  const byDecade = new Map(decades.map(d => [d.decade, d.share]));
  const first = Math.min(...decades.map(d => d.decade));
  const last = Math.max(...decades.map(d => d.decade));
  const all: number[] = [];
  for (let d = first; d <= last; d += 10) all.push(d);
  const percents = wholePercents(all.map(d => byDecade.get(d) ?? 0));
  const top = Math.max(...all.map(d => byDecade.get(d) ?? 0));
  return all.map((decade, i) => {
    const share = byDecade.get(decade) ?? 0;
    return {
      decade,
      percent: percents[i]!,
      height: top > 0 ? share / top : 0,
      peak: share === top && top > 0,
    };
  });
}

/** The decade with the largest share, or null. */
export function peakDecade(
  decades: readonly {decade: number; share: number}[],
): number | null {
  let best: {decade: number; share: number} | null = null;
  for (const d of decades) if (!best || d.share > best.share) best = d;
  return best?.decade ?? null;
}

/** Where a shared Nexus link points: the Library, where anyone can make theirs. */
export function nexusUrl(origin: string): string {
  return `${origin.replace(/\/$/, '')}/library#your-nexus`;
}
