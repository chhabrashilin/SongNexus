/**
 * An artist's external links, grouped by what they are for and named the way
 * listeners know them ("Spotify", not "open.spotify.com"). Duplicates collapse:
 * three Discogs entries become one, and a data-source link is only kept when it
 * really points at that source.
 */
import {hostOf} from '../components/evidence';

export type LinkGroup = 'listen' | 'official' | 'social' | 'reference';

export const LINK_GROUPS: LinkGroup[] = [
  'listen',
  'official',
  'social',
  'reference',
];

export interface NamedLink {
  url: string;
  /** A brand name, or the host when we don't know the site. */
  name: string;
  group: LinkGroup;
}

interface Brand {
  id: string;
  name: string;
  group: LinkGroup;
  /** Host suffixes (the host equals one or ends with "." + one). */
  hosts: string[];
}

/** Proper names of sites; listed in the order a group shows them. */
const BRANDS: Brand[] = [
  {
    id: 'youtube-music',
    name: 'YouTube Music',
    group: 'listen',
    hosts: ['music.youtube.com'],
  },
  {
    id: 'youtube',
    name: 'YouTube',
    group: 'listen',
    hosts: ['youtube.com', 'youtu.be'],
  },
  {id: 'spotify', name: 'Spotify', group: 'listen', hosts: ['spotify.com']},
  {
    id: 'apple-music',
    name: 'Apple Music',
    group: 'listen',
    hosts: ['music.apple.com', 'itunes.apple.com'],
  },
  {
    id: 'amazon-music',
    name: 'Amazon Music',
    group: 'listen',
    hosts: [
      'music.amazon.com',
      'music.amazon.co.uk',
      'music.amazon.de',
      'music.amazon.co.jp',
    ],
  },
  {id: 'deezer', name: 'Deezer', group: 'listen', hosts: ['deezer.com']},
  {id: 'tidal', name: 'TIDAL', group: 'listen', hosts: ['tidal.com']},
  {
    id: 'soundcloud',
    name: 'SoundCloud',
    group: 'listen',
    hosts: ['soundcloud.com'],
  },
  {id: 'bandcamp', name: 'Bandcamp', group: 'listen', hosts: ['bandcamp.com']},
  {id: 'qobuz', name: 'Qobuz', group: 'listen', hosts: ['qobuz.com']},
  {id: 'napster', name: 'Napster', group: 'listen', hosts: ['napster.com']},
  {
    id: 'audiomack',
    name: 'Audiomack',
    group: 'listen',
    hosts: ['audiomack.com'],
  },
  {id: 'anghami', name: 'Anghami', group: 'listen', hosts: ['anghami.com']},
  {
    id: 'boomplay',
    name: 'Boomplay',
    group: 'listen',
    hosts: ['boomplay.com', 'boomplaymusic.com'],
  },
  {id: 'melon', name: 'Melon', group: 'listen', hosts: ['melon.com']},
  {id: 'bugs', name: 'Bugs', group: 'listen', hosts: ['bugs.co.kr']},
  {
    id: 'instagram',
    name: 'Instagram',
    group: 'social',
    hosts: ['instagram.com'],
  },
  {id: 'x', name: 'X', group: 'social', hosts: ['x.com', 'twitter.com']},
  {id: 'tiktok', name: 'TikTok', group: 'social', hosts: ['tiktok.com']},
  {id: 'facebook', name: 'Facebook', group: 'social', hosts: ['facebook.com']},
  {id: 'threads', name: 'Threads', group: 'social', hosts: ['threads.net']},
  {id: 'weibo', name: 'Weibo', group: 'social', hosts: ['weibo.com']},
  {id: 'vk', name: 'VK', group: 'social', hosts: ['vk.com']},
  {id: 'myspace', name: 'Myspace', group: 'social', hosts: ['myspace.com']},
  {
    id: 'wikipedia',
    name: 'Wikipedia',
    group: 'reference',
    hosts: ['wikipedia.org'],
  },
  {
    id: 'musicbrainz',
    name: 'MusicBrainz',
    group: 'reference',
    hosts: ['musicbrainz.org'],
  },
  {id: 'discogs', name: 'Discogs', group: 'reference', hosts: ['discogs.com']},
  {
    id: 'wikidata',
    name: 'Wikidata',
    group: 'reference',
    hosts: ['wikidata.org'],
  },
  {
    id: 'allmusic',
    name: 'AllMusic',
    group: 'reference',
    hosts: ['allmusic.com'],
  },
  {id: 'genius', name: 'Genius', group: 'reference', hosts: ['genius.com']},
  {id: 'lastfm', name: 'Last.fm', group: 'reference', hosts: ['last.fm']},
  {
    id: 'listenbrainz',
    name: 'ListenBrainz',
    group: 'reference',
    hosts: ['listenbrainz.org'],
  },
  {
    id: 'songkick',
    name: 'Songkick',
    group: 'reference',
    hosts: ['songkick.com'],
  },
  {
    id: 'setlistfm',
    name: 'setlist.fm',
    group: 'reference',
    hosts: ['setlist.fm'],
  },
  {
    id: 'whosampled',
    name: 'WhoSampled',
    group: 'reference',
    hosts: ['whosampled.com'],
  },
  {
    id: 'secondhandsongs',
    name: 'SecondHandSongs',
    group: 'reference',
    hosts: ['secondhandsongs.com'],
  },
  {
    id: 'rateyourmusic',
    name: 'Rate Your Music',
    group: 'reference',
    hosts: ['rateyourmusic.com'],
  },
  {id: 'imdb', name: 'IMDb', group: 'reference', hosts: ['imdb.com']},
];

function brandOf(url: string): Brand | null {
  let host: string;
  try {
    host = new URL(url).hostname.toLowerCase();
  } catch {
    return null;
  }
  return (
    BRANDS.find(brand =>
      brand.hosts.some(h => host === h || host.endsWith(`.${h}`)),
    ) ?? null
  );
}

/** The group for a link on a site we don't know, from MusicBrainz's link type. */
function groupOfType(linkType: string): LinkGroup {
  const type = linkType.toLowerCase();
  if (type.includes('official')) return 'official';
  if (type.includes('social') || type.includes('blog')) return 'social';
  if (
    type.includes('stream') ||
    type.includes('download') ||
    type.includes('purchase')
  )
    return 'listen';
  return 'reference';
}

function normalized(id: string): string {
  return id.replace(/[^a-z]/gi, '').toLowerCase();
}

/** Safe to open: only web links. */
function isWeb(url: string): boolean {
  return /^https?:\/\//i.test(url);
}

export function groupLinks(
  links: {linkType: string; url: string}[],
  sources: {source: string; url: string}[] = [],
): [LinkGroup, NamedLink[]][] {
  const all: (NamedLink & {order: number})[] = [];
  const seen = new Set<string>();
  const add = (link: NamedLink, order: number) => {
    const key = `${link.group}:${link.name.toLowerCase()}`;
    if (seen.has(key) || !isWeb(link.url)) return;
    seen.add(key);
    all.push({...link, order});
  };

  for (const link of links) {
    const brand = brandOf(link.url);
    // An "official homepage" stays official even on a site we know.
    const group = groupOfType(link.linkType);
    if (brand && group !== 'official') {
      add(
        {url: link.url, name: brand.name, group: brand.group},
        BRANDS.indexOf(brand),
      );
    } else {
      add(
        {url: link.url, name: brand?.name ?? hostOf(link.url), group},
        BRANDS.length,
      );
    }
  }
  for (const source of sources) {
    const brand = brandOf(source.url);
    // A source whose URL is on another source's site is a broken link: skip it.
    if (brand && normalized(brand.id) !== normalized(source.source)) continue;
    add(
      {
        url: source.url,
        name: brand?.name ?? hostOf(source.url),
        group: 'reference',
      },
      brand ? BRANDS.indexOf(brand) : BRANDS.length,
    );
  }

  return LINK_GROUPS.map(
    group =>
      [
        group,
        all
          .filter(link => link.group === group)
          .sort((a, b) => a.order - b.order)
          .map(({url, name, group: g}) => ({url, name, group: g})),
      ] as [LinkGroup, NamedLink[]],
  ).filter(([, list]) => list.length > 0);
}
