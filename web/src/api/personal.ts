/**
 * Friend paths and "Your Nexus" (the taste profile). Friend paths need both
 * people to share their top artists (off by default); the taste profile is the
 * signed-in listener's own, or computed statelessly from artists a signed-out
 * listener matched on their device.
 */
import {useMutation, useQuery, useQueryClient} from '@tanstack/react-query';

import {api, unwrap, type Schemas} from './client';
import {lastId} from './social';

export type FriendPaths = Schemas['FriendPaths'];
export type FriendPath = Schemas['FriendPath'];
export type TasteProfile = Schemas['TasteProfile'];

/** How your top artists connect to a friend's (`users/{id}` or the id). */
export function useFriendPaths(friend: string | undefined) {
  return useQuery({
    queryKey: ['me', 'social', 'paths', friend],
    queryFn: () =>
      unwrap(
        api.GET('/v1/users/{user}/friends/{friend}/paths', {
          params: {path: {user: 'me', friend: lastId(friend!)}},
        }),
      ),
    enabled: Boolean(friend),
    retry: false,
    staleTime: 5 * 60_000,
  });
}

/** Turns "friends can see how our top artists connect" on or off. */
export function useShareTopArtists() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (shareTopArtists: boolean) =>
      unwrap(
        api.PATCH('/v1/users/{user}/socialProfile', {
          params: {path: {user: 'me'}},
          body: {shareTopArtists},
        }),
      ),
    onSuccess: data => {
      queryClient.setQueryData(['me', 'social', 'profile'], data);
      void queryClient.invalidateQueries({queryKey: ['me', 'social', 'paths']});
    },
  });
}

/** The signed-in listener's profile, from their linked accounts' listening. */
export function useTasteProfile(enabled: boolean) {
  return useQuery({
    queryKey: ['me', 'tasteProfile'],
    queryFn: () =>
      unwrap(
        api.GET('/v1/users/{user}/tasteProfile', {
          params: {path: {user: 'me'}},
        }),
      ),
    enabled,
    staleTime: 10 * 60_000,
  });
}

/** Profiles artists matched on this device; nothing is stored on the server. */
export function useComputeTasteProfile() {
  return useMutation({
    mutationFn: (artists: string[]) =>
      unwrap(api.POST('/v1/tasteProfiles:compute', {body: {artists}})),
  });
}
