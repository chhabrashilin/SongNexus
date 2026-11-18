/** Around you hooks: the campus and city directory, community charts, and your memberships. */
import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query';

import {api, unwrap, type Schemas} from './client';

export type Community = Schemas['Community'];
export type CommunityKind = Schemas['CommunityKind'];
export type CommunityChart = Schemas['CommunityChart'];
export type ChartArtist = Schemas['CommunityChartArtist'];
export type ListenerRange = Schemas['ListenerRange'];
export type UserCommunities = Schemas['UserCommunities'];

const MINUTE = 60_000;

/** The slug at the end of a community name (`communities/uw` -> `uw`). */
export function communityId(name: string): string {
  return name.slice(name.lastIndexOf('/') + 1);
}

/** Searches campuses or cities (largest first when the query is empty). */
export function useCommunities(
  query: string,
  kind: CommunityKind,
  country = '',
  demo = false,
) {
  return useQuery({
    queryKey: ['communities', kind, query, country, demo],
    queryFn: () =>
      unwrap(
        api.GET('/v1/communities', {
          params: {
            query: {
              query,
              kind,
              country,
              ...(demo ? {synthetic: true} : {}),
              pageSize: 50,
            },
          },
        }),
      ),
    placeholderData: keepPreviousData,
    staleTime: 60 * MINUTE,
  });
}

export function useCommunity(id: string | undefined) {
  return useQuery({
    queryKey: ['community', id],
    queryFn: () =>
      unwrap(
        api.GET('/v1/communities/{community}', {
          params: {path: {community: id!}},
        }),
      ),
    enabled: Boolean(id),
    staleTime: 60 * MINUTE,
  });
}

/**
 * Puts a community the page already has (a picked card) into the cache, so
 * opening it draws its page at once instead of flashing loading placeholders
 * while the same record is fetched again.
 */
export function useSeedCommunity() {
  const queryClient = useQueryClient();
  return (id: string, community: Community) => {
    if (queryClient.getQueryData(['community', id]) === undefined)
      queryClient.setQueryData(['community', id], community);
  };
}

/** A community's chart. Charts are recomputed on the server at most hourly. */
export function useCommunityChart(id: string | undefined) {
  return useQuery({
    queryKey: ['community', id, 'chart'],
    queryFn: () =>
      unwrap(
        api.GET('/v1/communities/{community}/chart', {
          params: {path: {community: id!}},
        }),
      ),
    enabled: Boolean(id),
    staleTime: 5 * MINUTE,
  });
}

export function useMyCommunities(enabled: boolean) {
  return useQuery({
    queryKey: ['me', 'communities'],
    queryFn: () =>
      unwrap(
        api.GET('/v1/users/{user}/communities', {
          params: {path: {user: 'me'}},
        }),
      ),
    enabled,
  });
}

export type MembershipField = 'campus' | 'city';

/** Joins (a community name) or leaves ('') your campus or city. */
export function useUpdateMyCommunities() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({field, value}: {field: MembershipField; value: string}) =>
      unwrap(
        api.PATCH('/v1/users/{user}/communities', {
          params: {path: {user: 'me'}, query: {updateMask: field}},
          body: {[field]: value},
        }),
      ),
    onSuccess: data => {
      queryClient.setQueryData(['me', 'communities'], data);
      void queryClient.invalidateQueries({queryKey: ['community']});
    },
  });
}

export type WeeklyMovers = Schemas['WeeklyMovers'];
export type ChartMover = Schemas['ChartMover'];

/** The chart's rises, falls, entries and exits since a week ago. */
export function useWeeklyMovers(id: string | undefined) {
  return useQuery({
    queryKey: ['community', id, 'movers'],
    queryFn: () =>
      unwrap(
        api.GET('/v1/communities/{community}/weeklyMovers', {
          params: {path: {community: id!}},
        }),
      ),
    enabled: Boolean(id),
    staleTime: 5 * MINUTE,
  });
}
