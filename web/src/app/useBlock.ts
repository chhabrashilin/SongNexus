/** Block or unblock an artist with an Undo snackbar (US-17). Signed-in users only in R1. */
import {useCallback} from 'react';

import type {ArtistSummary} from '../api/client';
import {idOf} from '../api/client';
import {
  useBlockArtist,
  useBlockedArtists,
  useUnblockArtist,
} from '../api/queries';
import {useAuth} from '../auth/AuthProvider';
import {useSnackbar} from '../components/Snackbar';
import {useI18n} from '../i18n/i18n';

export function useBlock(artist: ArtistSummary | undefined) {
  const {t} = useI18n();
  const auth = useAuth();
  const snackbar = useSnackbar();
  const signedIn = auth.status === 'signedIn';
  const list = useBlockedArtists(signedIn);
  const block = useBlockArtist();
  const unblock = useUnblockArtist();
  const id = artist ? idOf(artist.name) : '';
  const blocked = Boolean(
    list.data?.blockedArtists.some(b => b.name.endsWith(`/${id}`)),
  );

  const toggle = useCallback(async () => {
    if (!artist) return;
    if (!signedIn) {
      await auth.signIn();
      return;
    }
    const name = artist.displayName;
    if (blocked) {
      await unblock.mutateAsync(id);
      snackbar(t('block.undone', {name}));
    } else {
      await block.mutateAsync(id);
      snackbar(t('block.done', {name}), {
        label: t('action.undo'),
        onAction: () => void unblock.mutateAsync(id),
      });
    }
  }, [artist, auth, block, blocked, id, signedIn, snackbar, t, unblock]);

  return {blocked, toggle, busy: block.isPending || unblock.isPending};
}
