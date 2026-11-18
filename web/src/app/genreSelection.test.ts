import {describe, expect, it} from 'vitest';

import {
  NO_GENRE_FILTER,
  isFiltered,
  readGenreSelection,
  writeGenreSelection,
} from './genreSelection';

describe('genre selection in the URL', () => {
  it('defaults to no filter, with unknown genres and subgenres included', () => {
    expect(readGenreSelection(new URLSearchParams(''))).toEqual(
      NO_GENRE_FILTER,
    );
  });

  it('round-trips through the URL and keeps unrelated parameters', () => {
    const selection = {
      genres: ['genres/a', 'genres/b'],
      includeUnknownGenre: false,
      includeSubgenres: false,
    };
    const url = writeGenreSelection(new URLSearchParams('a=1&b=2'), selection);
    expect(url.get('a')).toBe('1');
    expect(readGenreSelection(url)).toEqual(selection);
  });

  it('leaves defaults out of the URL, so shared links stay short', () => {
    const url = writeGenreSelection(
      new URLSearchParams('genres=genres/a&unknown=0&subgenres=0'),
      NO_GENRE_FILTER,
    );
    expect(url.toString()).toBe('');
    expect(isFiltered(NO_GENRE_FILTER)).toBe(false);
  });
});
