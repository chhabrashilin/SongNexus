/**
 * Theme: SYSTEM follows the OS; LIGHT and DARK pin it via data-theme on <html>.
 * Signed-in users' choice follows their account; otherwise it's remembered locally.
 */
import {useEffect, useSyncExternalStore} from 'react';

import {usePreferences} from '../api/queries';
import {useAuth} from '../auth/AuthProvider';

export type Theme = 'SYSTEM' | 'LIGHT' | 'DARK';

const KEY = 'songnexus.theme';
const listeners = new Set<() => void>();

function readLocal(): Theme {
  try {
    const value = localStorage.getItem(KEY);
    return value === 'LIGHT' || value === 'DARK' ? value : 'SYSTEM';
  } catch {
    return 'SYSTEM';
  }
}

let current: Theme =
  typeof localStorage === 'undefined' ? 'SYSTEM' : readLocal();

export function applyTheme(theme: Theme): void {
  current = theme;
  try {
    localStorage.setItem(KEY, theme);
  } catch {
    // Storage may be unavailable (private mode); the choice still applies now.
  }
  const root = document.documentElement;
  if (theme === 'SYSTEM') delete root.dataset.theme;
  else root.dataset.theme = theme.toLowerCase();
  listeners.forEach(listener => listener());
}

export function useTheme(): Theme {
  return useSyncExternalStore(
    listener => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    () => current,
  );
}

/** Applies the stored theme on load and follows the account's preference once signed in. */
export function ThemeSync() {
  const auth = useAuth();
  const preferences = usePreferences(auth.status === 'signedIn');
  const accountTheme = preferences.data?.theme;
  useEffect(() => applyTheme(current), []);
  useEffect(() => {
    if (accountTheme) applyTheme(accountTheme);
  }, [accountTheme]);
  return null;
}
