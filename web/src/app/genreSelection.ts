/**
 * The genre filter (US-12), shared by Explore, Six degrees, Compare and Collaborations.
 *
 * Kept in the URL where a screen is shareable, so a link shows the same filtered
 * result to anyone: `genres` (comma-separated resource names), `unknown=0` to drop
 * artists without genre data, `subgenres=0` to match selected genres exactly.
 */
import {useCallback, useMemo} from 'react';
import {useSearchParams} from 'react-router';

export interface GenreSelection {
  genres: string[];
  includeUnknownGenre: boolean;
  includeSubgenres: boolean;
}

export const NO_GENRE_FILTER: GenreSelection = {
  genres: [],
  includeUnknownGenre: true,
  includeSubgenres: true,
};

export function readGenreSelection(search: URLSearchParams): GenreSelection {
  return {
    genres: (search.get('genres') ?? '').split(',').filter(Boolean),
    includeUnknownGenre: search.get('unknown') !== '0',
    includeSubgenres: search.get('subgenres') !== '0',
  };
}

/** Returns `search` with the selection written in; defaults are left out of the URL. */
export function writeGenreSelection(
  search: URLSearchParams,
  selection: GenreSelection,
): URLSearchParams {
  const next = new URLSearchParams(search);
  const set = (key: string, value: string | null) =>
    value === null ? next.delete(key) : next.set(key, value);
  set('genres', selection.genres.length ? selection.genres.join(',') : null);
  set('unknown', selection.includeUnknownGenre ? null : '0');
  set('subgenres', selection.includeSubgenres ? null : '0');
  return next;
}

export function isFiltered(selection: GenreSelection): boolean {
  return selection.genres.length > 0;
}

/** The genre selection held in the URL, and a setter that replaces the history entry. */
export function useGenreSelection(): [
  GenreSelection,
  (next: GenreSelection) => void,
] {
  const [search, setSearch] = useSearchParams();
  const selection = useMemo(() => readGenreSelection(search), [search]);
  const update = useCallback(
    (next: GenreSelection) =>
      setSearch(current => writeGenreSelection(current, next), {
        replace: true,
      }),
    [setSearch],
  );
  return [selection, update];
}
