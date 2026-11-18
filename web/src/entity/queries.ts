/**
 * Data hooks for the entity pages that the shared `api/queries.ts` does not
 * carry: explained recommendations and the genre page. Catalog answers, so they
 * are cached like the other catalog reads (they change only with the graph).
 */
import {useInfiniteQuery, useQuery} from '@tanstack/react-query';

import {api, unwrap} from '../api/client';

const MINUTE = 60_000;
const CATALOG_CACHE = {staleTime: 30 * MINUTE, gcTime: 60 * MINUTE} as const;

/** Artists to try next, each with checkable reasons. */
export function useRecommendations(
  artistId: string | undefined,
  pageSize = 20,
) {
  return useQuery({
    queryKey: ['recommendations', artistId, pageSize],
    queryFn: () =>
      unwrap(
        api.GET('/v1/artists/{artist}:recommend', {
          params: {path: {artist: artistId!}, query: {pageSize}},
        }),
      ),
    enabled: Boolean(artistId),
    ...CATALOG_CACHE,
  });
}

export function useGenre(id: string | undefined) {
  return useQuery({
    queryKey: ['genre', id],
    queryFn: () =>
      unwrap(api.GET('/v1/genres/{genre}', {params: {path: {genre: id!}}})),
    enabled: Boolean(id),
    ...CATALOG_CACHE,
  });
}

/** A genre's artists, most connected first, a page at a time. */
export const GENRE_PAGE = 24;

export function useGenreArtists(id: string | undefined) {
  return useInfiniteQuery({
    queryKey: ['genreArtists', id],
    initialPageParam: '',
    queryFn: ({pageParam}) =>
      unwrap(
        api.GET('/v1/genres/{genre}/artists', {
          params: {
            path: {genre: id!},
            query: {pageSize: GENRE_PAGE, pageToken: pageParam},
          },
        }),
      ),
    getNextPageParam: last => last.nextPageToken || undefined,
    enabled: Boolean(id),
    ...CATALOG_CACHE,
  });
}
