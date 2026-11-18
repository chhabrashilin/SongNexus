/**
 * Hover/focus prefetch: after a short intent delay on a link to an artist page,
 * warm the artist query so the page opens instantly. Leaving or blurring before
 * the delay cancels it, so skimming past a list fetches nothing.
 */
import {useQueryClient} from '@tanstack/react-query';
import {useCallback, useEffect, useRef} from 'react';

import {prefetchArtist} from '../api/queries';

export const INTENT_DELAY_MS = 120;

const ARTIST_PATH = /^\/artist\/([^/?#]+)/;

/** The artist ID in an app path like `/artist/{id}`, or null for any other path. */
export function artistIdFromPath(path: string): string | null {
  return ARTIST_PATH.exec(path)?.[1] ?? null;
}

export function useIntentPrefetch(artistId: string | null) {
  const queryClient = useQueryClient();
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  const cancel = useCallback(() => {
    clearTimeout(timer.current);
    timer.current = undefined;
  }, []);

  const start = useCallback(() => {
    if (!artistId || timer.current !== undefined) return;
    timer.current = setTimeout(() => {
      timer.current = undefined;
      void prefetchArtist(queryClient, artistId);
    }, INTENT_DELAY_MS);
  }, [artistId, queryClient]);

  useEffect(() => cancel, [cancel]);

  return {
    onPointerEnter: start,
    onPointerLeave: cancel,
    onFocus: start,
    onBlur: cancel,
  };
}
