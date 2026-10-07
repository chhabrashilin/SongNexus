/** Recently viewed artists, kept only in this browser (never sent to the server). */
import {useSyncExternalStore} from 'react';

import type {ArtistSummary} from '../api/client';

const KEY = 'songnexus.recent';
const MAX = 8;
const listeners = new Set<() => void>();

function read(): ArtistSummary[] {
  try {
    const parsed: unknown = JSON.parse(localStorage.getItem(KEY) ?? '[]');
    return Array.isArray(parsed)
      ? (parsed as ArtistSummary[]).slice(0, MAX)
      : [];
  } catch {
    return [];
  }
}

let snapshot: ArtistSummary[] =
  typeof localStorage === 'undefined' ? [] : read();

export function rememberArtist(artist: ArtistSummary): void {
  // Keep only the summary fields, even when given a full artist.
  const {name, displayName, disambiguation, artistType, country, genreKnown} =
    artist;
  const summary: ArtistSummary = {
    name,
    displayName,
    disambiguation,
    artistType,
    country,
    genreKnown,
  };
  snapshot = [summary, ...snapshot.filter(a => a.name !== name)].slice(0, MAX);
  try {
    localStorage.setItem(KEY, JSON.stringify(snapshot));
  } catch {
    // Storage unavailable: keep the in-memory list only.
  }
  listeners.forEach(listener => listener());
}

export function useRecentArtists(): ArtistSummary[] {
  return useSyncExternalStore(
    listener => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    () => snapshot,
  );
}
