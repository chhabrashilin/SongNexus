import {describe, expect, it} from 'vitest';

import {legacyDestination} from './legacyLinks';

describe('prototype share links', () => {
  const id = '00000000-0000-0000-0000-000000000001';
  it('maps puzzle links and bookmarks to Play', () => {
    expect(legacyDestination('?play=2026-10-08')).toBe('/play?date=2026-10-08');
    expect(legacyDestination('?tab=play')).toBe('/play');
  });
  it('maps artist and connection links without accepting invalid identifiers', () => {
    expect(legacyDestination(`?artist=${id}`)).toBe(`/explore/${id}`);
    expect(legacyDestination(`?from=${id}&to=invalid`)).toBe(
      `/six-degrees?from=${id}`,
    );
    expect(legacyDestination('?tab=admin')).toBeNull();
    expect(legacyDestination('?artist=invalid')).toBeNull();
    expect(legacyDestination('?tab=ask')).toBeNull();
    expect(legacyDestination('?tab=play&locale=ar-XB')).toBe(
      '/play?locale=ar-XB',
    );
  });
});
