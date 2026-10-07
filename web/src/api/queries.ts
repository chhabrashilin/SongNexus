/** Data hooks over the API (TanStack Query). One hook per method; keys include every parameter. */
import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
} from '@tanstack/react-query';

import {api, ApiError, unwrap, type Schemas} from './client';

export type ConnectionCategory = Schemas['ConnectionCategory'];
export type CollaborationType = Schemas['CollaborationType'];
export type PathMode = Schemas['PathMode'];

const MINUTE = 60_000;

/** Retries transient failures only; never client errors. */
export function shouldRetry(failureCount: number, error: unknown): boolean {
  if (error instanceof ApiError) {
    const transient = error.httpStatus === 0 || error.httpStatus >= 500;
    return transient && failureCount < 2;
  }
  return false;
}

export function useConfig() {
  return useQuery({
    queryKey: ['config'],
    queryFn: () => unwrap(api.GET('/v1/config')),
    staleTime: 5 * MINUTE,
  });
}

export function useArtist(id: string | undefined) {
  return useQuery({
    queryKey: ['artist', id],
    queryFn: () =>
      unwrap(api.GET('/v1/artists/{artist}', {params: {path: {artist: id!}}})),
    enabled: Boolean(id),
    staleTime: 5 * MINUTE,
  });
}

export interface ConnectionParams {
  categories: ConnectionCategory[];
  genres: string[];
  includeUnknownGenre: boolean;
  pageSize?: number;
  pageToken?: string;
}

export function fetchConnections(id: string, params: ConnectionParams) {
  return unwrap(
    api.GET('/v1/artists/{artist}/connections', {
      params: {path: {artist: id}, query: {...params}},
    }),
  );
}

export function useConnections(
  id: string | undefined,
  params: ConnectionParams,
) {
  return useQuery({
    queryKey: ['connections', id, params],
    queryFn: () => fetchConnections(id!, params),
    enabled: Boolean(id),
    staleTime: 5 * MINUTE,
    placeholderData: keepPreviousData,
  });
}

export function useConnection(
  a: string | undefined,
  b: string | undefined,
  categories: ConnectionCategory[],
) {
  return useQuery({
    queryKey: ['connection', a, b, categories],
    queryFn: () =>
      unwrap(
        api.GET('/v1/artists/{artist}/connections/{other}', {
          params: {path: {artist: a!, other: b!}, query: {categories}},
        }),
      ),
    enabled: Boolean(a && b),
    staleTime: 5 * MINUTE,
  });
}

export function useCollaborations(
  id: string | undefined,
  type: CollaborationType,
  pageToken = '',
) {
  return useQuery({
    queryKey: ['collaborations', id, type, pageToken],
    queryFn: () =>
      unwrap(
        api.GET('/v1/artists/{artist}/collaborations', {
          params: {path: {artist: id!}, query: {type, pageSize: 25, pageToken}},
        }),
      ),
    enabled: Boolean(id),
    staleTime: 5 * MINUTE,
    placeholderData: keepPreviousData,
  });
}

export interface PathParams {
  from: string;
  to: string;
  mode: PathMode;
  categories: ConnectionCategory[];
  genres: string[];
  includeUnknownGenre: boolean;
  alternatives: number;
}

export function usePath(params: PathParams | null) {
  return useQuery({
    queryKey: ['path', params],
    queryFn: () =>
      unwrap(
        api.GET('/v1/artists/{artist}:findPath', {
          params: {
            path: {artist: params!.from},
            query: {
              target: `artists/${params!.to}`,
              mode: params!.mode,
              categories: params!.categories,
              genres: params!.genres,
              includeUnknownGenre: params!.includeUnknownGenre,
              alternatives: params!.alternatives,
            },
          },
        }),
      ),
    enabled: params !== null,
    staleTime: 5 * MINUTE,
  });
}

export function useCompare(a: string | undefined, b: string | undefined) {
  return useQuery({
    queryKey: ['compare', a, b],
    queryFn: () =>
      unwrap(
        api.GET('/v1/artists/{artist}:compare', {
          params: {path: {artist: a!}, query: {other: `artists/${b!}`}},
        }),
      ),
    enabled: Boolean(a && b && a !== b),
    staleTime: 5 * MINUTE,
  });
}

export function useRecording(id: string | undefined) {
  return useQuery({
    queryKey: ['recording', id],
    queryFn: () =>
      unwrap(
        api.GET('/v1/recordings/{recording}', {
          params: {path: {recording: id!}},
        }),
      ),
    enabled: Boolean(id),
    staleTime: 5 * MINUTE,
  });
}

export function useSearch(query: string, types: Schemas['EntityType'][] = []) {
  const trimmed = query.trim();
  return useQuery({
    queryKey: ['search', trimmed, types],
    queryFn: ({signal}) =>
      unwrap(
        api.GET('/v1/catalog:search', {
          params: {query: {query: trimmed, types, pageSize: 8}},
          signal,
        }),
      ),
    enabled: trimmed.length > 0,
    staleTime: MINUTE,
    placeholderData: keepPreviousData,
  });
}

/** Every genre (the API pages at 100; the catalog has more). QA Q16. */
export async function fetchAllGenres(): Promise<Schemas['Genre'][]> {
  const genres: Schemas['Genre'][] = [];
  let pageToken = '';
  do {
    const page = await unwrap(
      api.GET('/v1/genres', {params: {query: {pageSize: 100, pageToken}}}),
    );
    genres.push(...page.genres);
    pageToken = page.nextPageToken;
  } while (pageToken);
  return genres;
}

export function useGenres() {
  return useQuery({
    queryKey: ['genres'],
    queryFn: fetchAllGenres,
    staleTime: 30 * MINUTE,
  });
}

// ---------------------------------------------------------------------------
// Signed-in user data
// ---------------------------------------------------------------------------

export function usePreferences(enabled: boolean) {
  return useQuery({
    queryKey: ['me', 'preferences'],
    queryFn: () =>
      unwrap(
        api.GET('/v1/users/{user}/preferences', {params: {path: {user: 'me'}}}),
      ),
    enabled,
  });
}

export function useUpdatePreferences() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      body,
      mask,
    }: {
      body: Schemas['Preferences-Input'];
      mask: string;
    }) =>
      unwrap(
        api.PATCH('/v1/users/{user}/preferences', {
          params: {path: {user: 'me'}, query: {updateMask: mask}},
          body,
        }),
      ),
    onSuccess: data => queryClient.setQueryData(['me', 'preferences'], data),
    onError: () =>
      queryClient.invalidateQueries({queryKey: ['me', 'preferences']}),
  });
}

export function useBlockedArtists(enabled: boolean) {
  return useQuery({
    queryKey: ['me', 'blocked'],
    queryFn: () =>
      unwrap(
        api.GET('/v1/users/{user}/blockedArtists', {
          params: {path: {user: 'me'}, query: {pageSize: 1000}},
        }),
      ),
    enabled,
  });
}

/** Blocks change what every list returns, so all catalog queries are refetched. */
function refreshAfterBlockChange(queryClient: QueryClient) {
  void queryClient.invalidateQueries({
    predicate: query =>
      query.queryKey[0] !== 'config' && query.queryKey[0] !== 'genres',
  });
}

export function useBlockArtist() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (artistId: string) =>
      unwrap(
        api.POST('/v1/users/{user}/blockedArtists', {
          params: {path: {user: 'me'}},
          body: {artist: `artists/${artistId}`},
        }),
      ),
    onSettled: () => refreshAfterBlockChange(queryClient),
  });
}

export function useUnblockArtist() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (artistId: string) =>
      unwrap(
        api.DELETE('/v1/users/{user}/blockedArtists/{artist}', {
          params: {path: {user: 'me', artist: artistId}},
        }),
      ),
    onSettled: () => refreshAfterBlockChange(queryClient),
  });
}

export function useProfile(enabled: boolean) {
  return useQuery({
    queryKey: ['me', 'profile'],
    queryFn: () =>
      unwrap(
        api.GET('/v1/users/{user}/profile', {params: {path: {user: 'me'}}}),
      ),
    enabled,
  });
}

export function useUpdateProfile() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: Schemas['Profile-Input']) =>
      unwrap(
        api.PATCH('/v1/users/{user}/profile', {
          params: {path: {user: 'me'}, query: {updateMask: 'topArtists'}},
          body,
        }),
      ),
    onSuccess: data => queryClient.setQueryData(['me', 'profile'], data),
    onError: () => queryClient.invalidateQueries({queryKey: ['me', 'profile']}),
  });
}
