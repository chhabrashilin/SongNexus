/**
 * How a campus or city looks everywhere it appears (cards, the community page,
 * You, leaderboards):
 *
 * - a campus shows the mark it is known by, from Wikimedia Commons: its
 *   athletics mark when there is one (Wisconsin's motion W, Illinois's block
 *   I), else its own logo or seal (campusLogos.json, built by
 *   scripts/fetch-campus-logos.mjs). A transparent mark sits bare on the card;
 *   one that would disappear on the current theme gets a plate (white on dark,
 *   near-black on light). Wide wordmarks get a wider tile;
 * - a city shows its landmark, drawn for SongNexus (landmarks.ts), or a skyline,
 *   with no tile: the silhouette itself carries the city's color;
 * - a campus without a logo shows its city's landmark.
 *
 * A logo that fails to load falls back to the landmark, never to a blank tile.
 */
import {useId, useState, type CSSProperties} from 'react';

import {hueOf} from '../components/ArtistRow';

import campusLogos from './campusLogos.json';
import {landmarkFor, SKYLINE, type Landmark} from './landmarks';

export interface CampusLogo {
  src: string;
  aspect: number;
  kind: 'athletics' | 'logo' | 'seal';
  /** The athletics program, for an athletics mark. */
  team?: string;
  /** Whether the mark needs a plate behind it on each theme. */
  plate: {dark: boolean; light: boolean};
  page: string;
  author: string;
  license: string;
  licenseUrl: string;
}

const LOGOS = campusLogos.logos as Record<string, CampusLogo>;
/** Wider than this, a logo gets a wide plate instead of a square one. */
const WIDE = 1.8;

export interface MarkedCommunity {
  /** Resource name, "communities/<id>". */
  name: string;
  kind?: 'CAMPUS' | 'CITY' | string;
  /** The campus's city, "communities/<id>". */
  cityCommunity?: string | null;
  shortName?: string;
  displayName: string;
}

const idOf = (name: string) => name.slice(name.lastIndexOf('/') + 1);

/** The campus's official logo, when Commons has a free one. */
export function campusLogo(community: MarkedCommunity): CampusLogo | null {
  return LOGOS[idOf(community.name)] ?? null;
}

function cityIdOf(community: MarkedCommunity): string {
  if (community.kind === 'CITY') return idOf(community.name);
  return community.cityCommunity ? idOf(community.cityCommunity) : '';
}

function LandmarkArt({landmark}: {landmark: Landmark}) {
  const mask = useId();
  const paint = useId();
  const cut = Boolean(landmark.holes?.length || landmark.holeLines?.length);
  // The silhouette itself carries the city's color, top to bottom; user-space
  // units so straight strokes (zero-width boxes) are painted too.
  const ink = `url(#${paint})`;
  return (
    <svg viewBox="0 0 64 64" aria-hidden="true" focusable="false">
      <linearGradient
        id={paint}
        gradientUnits="userSpaceOnUse"
        x1="20"
        y1="2"
        x2="44"
        y2="58"
      >
        <stop offset="0" className="landmark-ink-top" />
        <stop offset="1" className="landmark-ink-bottom" />
      </linearGradient>
      {cut && (
        <mask id={mask}>
          <rect width="64" height="64" fill="#fff" />
          {landmark.holes?.map((d, i) => (
            <path key={i} d={d} fill="#000" />
          ))}
          {landmark.holeLines?.map(([d, w], i) => (
            <path
              key={`l${i}`}
              d={d}
              fill="none"
              stroke="#000"
              strokeWidth={w}
              strokeLinecap="round"
            />
          ))}
        </mask>
      )}
      <g mask={cut ? `url(#${mask})` : undefined} fill={ink}>
        <rect x="5" y="56" width="54" height="1.4" opacity="0.35" />
        {landmark.soft?.map((d, i) => (
          <path key={`s${i}`} d={d} opacity="0.42" />
        ))}
        {landmark.fill?.map((d, i) => (
          <path key={`f${i}`} d={d} />
        ))}
        {landmark.lines?.map(([d, w], i) => (
          <path
            key={`k${i}`}
            d={d}
            fill="none"
            stroke={ink}
            strokeWidth={w}
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        ))}
      </g>
    </svg>
  );
}

export function CommunityMark({
  community,
  eager = false,
  allowWide = true,
}: {
  community: MarkedCommunity;
  /** Load the logo right away (above the fold). */
  eager?: boolean;
  /** Let a wide wordmark take a wide plate; off where the slot is square. */
  allowWide?: boolean;
}) {
  const [failed, setFailed] = useState(false);
  const logo = community.kind === 'CITY' ? null : campusLogo(community);

  if (logo && !failed) {
    const wide = allowWide && logo.aspect > WIDE;
    return (
      <span
        className="community-mark community-mark--logo"
        data-wide={wide || undefined}
        data-seal={logo.kind === 'seal' || undefined}
        data-plate-dark={logo.plate.dark || undefined}
        data-plate-light={logo.plate.light || undefined}
        aria-hidden="true"
      >
        <img
          src={logo.src}
          alt=""
          loading={eager ? 'eager' : 'lazy'}
          decoding="async"
          referrerPolicy="no-referrer"
          draggable={false}
          onError={() => setFailed(true)}
        />
      </span>
    );
  }

  const landmark = landmarkFor(cityIdOf(community));
  return (
    <span
      className="community-mark community-mark--place"
      style={
        {
          '--hue': hueOf(community.shortName || community.displayName),
        } as CSSProperties
      }
      title={landmark === SKYLINE ? undefined : landmark.name}
      aria-hidden="true"
    >
      <LandmarkArt landmark={landmark} />
    </span>
  );
}
