import {describe, expect, it} from 'vitest';

import {artistIdFromPath} from './useIntentPrefetch';

describe('artistIdFromPath', () => {
  it('reads the artist ID from an artist page path', () => {
    expect(artistIdFromPath('/artist/abc-123')).toBe('abc-123');
    expect(artistIdFromPath('/artist/abc-123?tab=x')).toBe('abc-123');
  });

  it('ignores every other path', () => {
    expect(artistIdFromPath('/explore/abc')).toBeNull();
    expect(artistIdFromPath('/artist/')).toBeNull();
  });
});
