/**
 * Starting points for someone who hasn't looked anyone up yet: a short,
 * editorial list of well-known artists across genres. The server owns the list
 * (`GET /v1/artists:featured`) and resolves it against the catalog in order, so
 * it never points at an artist we don't have, and Home needs one request.
 */
import {useQuery} from '@tanstack/react-query';

import {api, unwrap, type ArtistSummary} from '../api/client';

export type Starter = Pick<ArtistSummary, 'name' | 'displayName'>;

const NONE: Starter[] = [];

/** The starter artists that exist in the catalog, in editorial order. */
export function useStarterArtists(enabled = true): Starter[] {
  const {data} = useQuery({
    queryKey: ['featuredArtists'],
    queryFn: () => unwrap(api.GET('/v1/artists:featured')),
    enabled,
    staleTime: 30 * 60_000,
    gcTime: 60 * 60_000,
    retry: false,
  });
  return (
    data?.artists.map(({name, displayName}) => ({name, displayName})) ?? NONE
  );
}
