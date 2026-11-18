/** Pure helpers for Home's shelves: which to show, in what order. */
import type {Schemas} from '../api/client';

type Shelf = Schemas['Shelf'];

/** How many genre and decade shelves Home shows (the server sends every one). */
export const MAX_GENRES = 4;
export const MAX_DECADES = 3;

/**
 * Home's order: the editorial shelves first, then genres and decades taken in
 * turn so the page alternates instead of showing a block of each, then labels.
 * The server orders genres by size and decades newest first; that order is kept.
 */
export function curate(shelves: readonly Shelf[]): Shelf[] {
  const usable = shelves.filter(shelf => shelf.items.length > 0);
  const of = (kind: Shelf['kind']) => usable.filter(s => s.kind === kind);
  const genres = of('GENRE').slice(0, MAX_GENRES);
  const decades = of('DECADE').slice(0, MAX_DECADES);
  const alternating: Shelf[] = [];
  for (let i = 0; i < Math.max(genres.length, decades.length); i++) {
    if (genres[i]) alternating.push(genres[i]!);
    if (decades[i]) alternating.push(decades[i]!);
  }
  return [
    ...of('BEHIND_THE_HITS'),
    ...of('ON_THIS_DAY'),
    ...of('SUPER_CONNECTORS'),
    ...alternating.slice(0, 2),
    ...of('GENRE_BRIDGES'),
    ...alternating.slice(2),
    ...of('LABELS'),
  ];
}

/** A local calendar date ("2026-11-16") as a Date at local noon, for formatting. */
export function shelfDate(date: string): Date {
  const [year = 1970, month = 1, day = 1] = date.split('-').map(Number);
  return new Date(year, month - 1, day, 12);
}
