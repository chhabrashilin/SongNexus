/** Regression tests for web findings from the QA review (docs/qa/2026-10-07-review.md). */
import {afterEach, describe, expect, it, vi} from 'vitest';

import {fetchAllGenres} from '../api/queries';

import {isChunkLoadError} from './RouteError';

function json(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: {'Content-Type': 'application/json'},
  });
}

describe('Q14: stale-chunk detection', () => {
  it('recognizes chunk-load failures in each browser', () => {
    expect(
      isChunkLoadError(
        new TypeError(
          'Failed to fetch dynamically imported module: /assets/A.js',
        ),
      ),
    ).toBe(true);
    expect(
      isChunkLoadError(new TypeError('Importing a module script failed.')),
    ).toBe(true);
    expect(
      isChunkLoadError(new Error('error loading dynamically imported module')),
    ).toBe(true);
  });

  it('leaves other errors to the error message', () => {
    expect(
      isChunkLoadError(new Error('Cannot read properties of undefined')),
    ).toBe(false);
  });
});

describe('Q16: genres', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('fetches every page, not just the first', async () => {
    const genre = (i: number) => ({
      name: `genres/${i}`,
      displayName: `g${i}`,
      artistCount: 1,
    });
    const fetchMock = vi.fn((input: Request) => {
      const token = new URL(input.url).searchParams.get('pageToken');
      return Promise.resolve(
        token
          ? json({genres: [genre(101)], nextPageToken: '', totalSize: 101})
          : json({
              genres: Array.from({length: 100}, (_, i) => genre(i)),
              nextPageToken: 'next',
              totalSize: 101,
            }),
      );
    });
    vi.stubGlobal('fetch', fetchMock);
    const all = await fetchAllGenres();
    expect(all).toHaveLength(101);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
