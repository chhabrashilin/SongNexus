import {describe, expect, it} from 'vitest';

import type {Share} from '../api/social';
import {createI18n} from '../i18n/i18n';
import {ago, shareTitle} from '../screens/FriendsScreen';

import {sharePath} from './ShareSheet';

const {t} = createI18n('en-US');

function share(kind: Share['kind'], names: string[]): Share {
  return {
    name: 'shares/1',
    kind,
    note: '',
    read: false,
    createTime: '2026-11-13T10:00:00Z',
    sender: {user: 'users/a', displayName: 'Ana'},
    recipient: {user: 'users/b', displayName: 'Ben'},
    subjects: names.map((displayName, i) => ({
      name: `artists/${i}`,
      displayName,
      available: displayName !== '',
    })),
  };
}

describe('sharing', () => {
  it('opens each kind of share at the page it came from', () => {
    expect(sharePath('ARTIST', ['artists/a'])).toBe('/artist/a');
    expect(sharePath('RECORDING', ['recordings/r'])).toBe('/song/r');
    expect(sharePath('ARTIST_COMPARISON', ['artists/a', 'artists/b'])).toBe(
      '/compare?a=a&b=b',
    );
    expect(
      sharePath('RECORDING_COMPARISON', ['recordings/x', 'recordings/y']),
    ).toBe('/compare/songs?a=x&b=y');
    expect(sharePath('PATH', ['artists/a', 'artists/b'])).toBe(
      '/six-degrees?from=a&to=b',
    );
  });

  it('titles shares in a few words, and says when something is gone', () => {
    expect(shareTitle(t, share('ARTIST', ['Alice']))).toBe('Alice');
    expect(shareTitle(t, share('PATH', ['Alice', 'Bob']))).toBe('Alice → Bob');
    expect(shareTitle(t, share('ARTIST_COMPARISON', ['Alice', '']))).toBe(
      'Alice vs Not in our data anymore',
    );
  });

  it('says how long ago something was shared', () => {
    const now = Date.parse('2026-11-13T12:00:00Z');
    expect(ago(t, '2026-11-13T12:00:00Z', now)).toBe('just now');
    expect(ago(t, '2026-11-13T11:59:00Z', now)).toBe('1 minute ago');
    expect(ago(t, '2026-11-13T09:00:00Z', now)).toBe('3 hours ago');
    expect(ago(t, '2026-11-10T12:00:00Z', now)).toBe('3 days ago');
  });
});
