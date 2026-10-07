import {describe, expect, it} from 'vitest';

import type {Evidence} from '../api/client';
import {createI18n} from '../i18n/i18n';

import {evidenceText, hostOf} from './evidence';

const {t} = createI18n('en-US');
const names: Record<string, string> = {
  'artists/k': 'Kendrick Lamar',
  'artists/s': 'SZA',
};
const nameOf = (n: string) => names[n] ?? n;

function line(partial: Partial<Evidence>): Evidence {
  return {
    messageId: 'evidence.featured',
    kind: 'PERFORMED_WITH',
    fromArtist: 'artists/k',
    toArtist: 'artists/s',
    fromRole: 'primary',
    toRole: 'featured',
    subject: {name: 'recordings/r', displayName: 'Doves in the Wind'},
    sources: [],
    ...partial,
  };
}

describe('evidenceText', () => {
  it('orients featured credits by role', () => {
    expect(evidenceText(line({}), nameOf, t)).toBe(
      'SZA is featured on Kendrick Lamar’s “Doves in the Wind”',
    );
    const reversed = line({
      fromArtist: 'artists/s',
      toArtist: 'artists/k',
      fromRole: 'featured',
      toRole: 'primary',
    });
    expect(evidenceText(reversed, nameOf, t)).toBe(
      evidenceText(line({}), nameOf, t),
    );
  });

  it('names the contributor and their role', () => {
    const e = line({
      messageId: 'evidence.contributed',
      fromRole: 'primary',
      toRole: 'instrument',
    });
    expect(evidenceText(e, nameOf, t)).toBe(
      'SZA played an instrument on Kendrick Lamar’s “Doves in the Wind”',
    );
  });

  it('phrases relations from either side', () => {
    const member = line({
      messageId: 'evidence.relation',
      fromRole: 'member',
      toRole: 'group',
    });
    const group = line({
      messageId: 'evidence.relation',
      fromRole: 'group',
      toRole: 'member',
    });
    expect(evidenceText(member, nameOf, t)).toBe(
      'Kendrick Lamar is a member of SZA',
    );
    expect(evidenceText(group, nameOf, t)).toBe(
      'SZA is a member of Kendrick Lamar',
    );
  });

  it('falls back when the subject has no title', () => {
    const e = line({
      messageId: 'evidence.performedTogether',
      subject: {name: 'releases/x', displayName: null},
    });
    expect(evidenceText(e, nameOf, t)).toBe(
      'Kendrick Lamar and SZA are both credited on an album',
    );
  });

  it('never throws on unknown message IDs', () => {
    expect(evidenceText(line({messageId: 'evidence.future'}), nameOf, t)).toBe(
      'Kendrick Lamar and SZA worked together',
    );
  });
});

describe('hostOf', () => {
  it('strips www and tolerates junk', () => {
    expect(hostOf('https://www.musicbrainz.org/recording/1')).toBe(
      'musicbrainz.org',
    );
    expect(hostOf('not a url')).toBe('not a url');
  });
});
