/** Friends and sharing hooks (R2-7, ADR 0007). Everything is the signed-in user's own. */
import {useMutation, useQuery, useQueryClient} from '@tanstack/react-query';

import {api, unwrap, type Schemas} from './client';

export type Share = Schemas['Share'];
export type ShareKind = Schemas['ShareKind'];
export type Friend = Schemas['Friend'];
export type ReportReason = Schemas['ReportReason'];

const MINUTE = 60_000;
const me = {params: {path: {user: 'me'}}} as const;

/** The ID at the end of a resource name (`users/me/friends/abc` -> `abc`). */
export function lastId(name: string): string {
  return name.slice(name.lastIndexOf('/') + 1);
}

function useInvalidate() {
  const queryClient = useQueryClient();
  return () => void queryClient.invalidateQueries({queryKey: ['me', 'social']});
}

export function useSocialProfile(enabled: boolean) {
  return useQuery({
    queryKey: ['me', 'social', 'profile'],
    queryFn: () => unwrap(api.GET('/v1/users/{user}/socialProfile', me)),
    enabled,
  });
}

export function useUpdateSocialProfile() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (displayName: string) =>
      unwrap(
        api.PATCH('/v1/users/{user}/socialProfile', {
          ...me,
          body: {displayName},
        }),
      ),
    onSuccess: invalidate,
  });
}

export function useFriends(enabled: boolean) {
  return useQuery({
    queryKey: ['me', 'social', 'friends'],
    queryFn: () =>
      unwrap(
        api.GET('/v1/users/{user}/friends', {
          params: {path: {user: 'me'}, query: {pageSize: 500}},
        }),
      ),
    enabled,
  });
}

export function useDeleteFriend() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (user: string) =>
      unwrap(
        api.DELETE('/v1/users/{user}/friends/{friend}', {
          params: {path: {user: 'me', friend: lastId(user)}},
        }),
      ),
    onSettled: invalidate,
  });
}

export function useFriendInvites(enabled: boolean) {
  return useQuery({
    queryKey: ['me', 'social', 'invites'],
    queryFn: () => unwrap(api.GET('/v1/users/{user}/friendInvites', me)),
    enabled,
  });
}

export function useCreateInvite() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: () => unwrap(api.POST('/v1/users/{user}/friendInvites', me)),
    onSuccess: invalidate,
  });
}

export function useDeleteInvite() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (name: string) =>
      unwrap(
        api.DELETE('/v1/users/{user}/friendInvites/{invite}', {
          params: {path: {user: 'me', invite: lastId(name)}},
        }),
      ),
    onSettled: invalidate,
  });
}

export function useInvitePreview(code: string, enabled: boolean) {
  return useQuery({
    queryKey: ['me', 'social', 'invite', code],
    queryFn: () =>
      unwrap(api.GET('/v1/friendInvites/{code}', {params: {path: {code}}})),
    enabled: enabled && code.length > 0,
    retry: false,
  });
}

export function useAcceptInvite() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (code: string) =>
      unwrap(
        api.POST('/v1/friendInvites/{code}:accept', {params: {path: {code}}}),
      ),
    onSuccess: invalidate,
  });
}

export function useBlockedUsers(enabled: boolean) {
  return useQuery({
    queryKey: ['me', 'social', 'blocked'],
    queryFn: () => unwrap(api.GET('/v1/users/{user}/blockedUsers', me)),
    enabled,
  });
}

export function useBlockUser() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (user: string) =>
      unwrap(api.POST('/v1/users/{user}/blockedUsers', {...me, body: {user}})),
    onSettled: invalidate,
  });
}

export function useUnblockUser() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (user: string) =>
      unwrap(
        api.DELETE('/v1/users/{user}/blockedUsers/{blocked}', {
          params: {path: {user: 'me', blocked: lastId(user)}},
        }),
      ),
    onSettled: invalidate,
  });
}

export function useInbox(enabled: boolean) {
  return useQuery({
    queryKey: ['me', 'social', 'inbox'],
    queryFn: () =>
      unwrap(
        api.GET('/v1/users/{user}/inbox', {
          params: {path: {user: 'me'}, query: {pageSize: 100}},
        }),
      ),
    enabled,
    refetchInterval: MINUTE,
  });
}

export function useMarkShareRead() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (name: string) =>
      unwrap(
        api.POST('/v1/shares/{share}:markRead', {
          params: {path: {share: lastId(name)}},
        }),
      ),
    onSuccess: invalidate,
  });
}

export function useMarkInboxRead() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: () => unwrap(api.POST('/v1/users/{user}/inbox:markRead', me)),
    onSuccess: invalidate,
  });
}

export function useDeleteShare() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (name: string) =>
      unwrap(
        api.DELETE('/v1/shares/{share}', {
          params: {path: {share: lastId(name)}},
        }),
      ),
    onSettled: invalidate,
  });
}

export function useCreateShare() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (body: Schemas['CreateShareRequest']) =>
      unwrap(api.POST('/v1/shares', {body})),
    onSuccess: invalidate,
  });
}

export function useReport() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (body: Schemas['CreateReportRequest']) =>
      unwrap(api.POST('/v1/reports', {body})),
    onSettled: invalidate,
  });
}
