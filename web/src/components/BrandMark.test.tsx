import {renderToStaticMarkup} from 'react-dom/server';
import {describe, expect, it} from 'vitest';

import type {ListeningProvider} from '../api/queries';

import {BrandMark} from './BrandMark';

const PROVIDERS: ListeningProvider[] = [
  'YOUTUBE_MUSIC',
  'SPOTIFY',
  'APPLE_MUSIC',
  'LASTFM',
  'LISTENBRAINZ',
  'DEEZER',
  'LIBREFM',
];

describe('BrandMark', () => {
  it.each(PROVIDERS)('draws %s as a decorative mark at the asked size', p => {
    const html = renderToStaticMarkup(<BrandMark provider={p} size={44} />);
    // React may put an image preload <link> first; the mark follows it.
    expect(html).toMatch(/<(svg|img) /);
    expect(html).toContain('aria-hidden="true"');
    expect(html).toContain('width="44"');
    expect(html).toContain(`data-provider="${p}"`);
    // A real mark, never the old two-letter monogram.
    expect(html).not.toMatch(/>[A-Za-z]{2}</);
  });

  it('serves the Commons logo files from /brands', () => {
    expect(
      renderToStaticMarkup(<BrandMark provider="LISTENBRAINZ" />),
    ).toContain('src="/brands/listenbrainz.svg"');
    expect(renderToStaticMarkup(<BrandMark provider="LIBREFM" />)).toContain(
      'href="/brands/librefm.svg"',
    );
  });
});
