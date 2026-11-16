/**
 * Starting points for someone who hasn't looked anyone up yet: a short,
 * editorial list of well-known artists across genres, resolved against the
 * catalog by name so the list never points at an artist we don't have.
 */
import {useQueries} from '@tanstack/react-query';

import {api, unwrap, type ArtistSummary} from '../api/client';

export const STARTER_NAMES = [
  'Kendrick Lamar',
  'Beyoncé',
  'Daft Punk',
  'Radiohead',
  'Taylor Swift',
  'Miles Davis',
  'Björk',
  'BTS',
  'Thundercat',
  'SZA',
  'David Bowie',
  'Rihanna',
] as const;

export type Starter = Pick<ArtistSummary, 'name' | 'displayName'>;

const sameName = (a: string, b: string) =>
  a.localeCompare(b, undefined, {sensitivity: 'base'}) === 0;

/** The starter artists that exist in the catalog, in editorial order. */
export function useStarterArtists(enabled = true): Starter[] {
  const results = useQueries({
    queries: STARTER_NAMES.map(query => ({
      queryKey: ['starter', query],
      queryFn: async (): Promise<Starter | null> => {
        const page = await unwrap(
          api.GET('/v1/catalog:search', {
            params: {query: {query, types: ['ARTIST'], pageSize: 1}},
          }),
        );
        const top = page.results?.[0];
        return top && sameName(top.displayName, query)
          ? {name: top.name, displayName: top.displayName}
          : null;
      },
      enabled,
      staleTime: Infinity,
      retry: false,
    })),
  });
  return results.flatMap(result => (result.data ? [result.data] : []));
}
