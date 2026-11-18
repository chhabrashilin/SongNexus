/**
 * Ambient color: a page about someone (an artist, a song, a story) washes the
 * top of the page in that subject's color. The hue lives in one custom property
 * on <html>; CSS animates between hues, so moving from one artist to the next
 * shifts the color instead of snapping.
 */
import {useEffect} from 'react';

import {hueOf} from '../components/ArtistRow';

/** The hue of pages that aren't about anyone in particular (the brand's red). */
export const DEFAULT_AMBIENT_HUE = 350;

/** Sets the page's ambient hue from a name (same hash as generated covers) or a number. */
export function useAmbient(subject: string | number | null | undefined): void {
  const hue =
    typeof subject === 'number'
      ? subject
      : subject
        ? hueOf(subject)
        : DEFAULT_AMBIENT_HUE;
  useEffect(() => {
    const root = document.documentElement;
    root.style.setProperty('--ambient-hue', String(hue));
    return () => {
      root.style.setProperty('--ambient-hue', String(DEFAULT_AMBIENT_HUE));
    };
  }, [hue]);
}
