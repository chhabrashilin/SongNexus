/**
 * A chain of portraits: artists in order, each linked to the next. Between two
 * portraits sits the link itself, which can open the credits behind it.
 */
import type {ArtistSummary} from '../api/client';
import {artistPath, imageOf} from '../components/ArtistRow';
import {Icon} from '../components/Icon';
import {Cover} from '../components/Shelf';
import {Link} from 'react-router';

export interface ChainLink {
  /** Short visible text on the link ("1 credit"). */
  text: string;
  /** What the link does, for assistive technology. */
  label: string;
  onOpen: () => void;
}

export function PortraitChain({
  artists,
  links,
  label,
  ends = true,
}: {
  artists: ArtistSummary[];
  /** One per gap between portraits; plain lines when absent. */
  links?: ChainLink[];
  label: string;
  /** Mark the first and last portraits as the two ends (larger, ringed). */
  ends?: boolean;
}) {
  return (
    <ol className="chain" aria-label={label}>
      {artists.map((artist, i) => {
        const link = i > 0 ? links?.[i - 1] : undefined;
        return (
          <li
            key={`${artist.name}-${i}`}
            className="chain__item"
            data-end={
              ends && (i === 0 || i === artists.length - 1) ? true : undefined
            }
          >
            {i > 0 && (
              <span className="chain__link">
                <span className="chain__line" aria-hidden="true" />
                {link && (
                  <button
                    type="button"
                    className="chain__credits"
                    aria-label={link.label}
                    onClick={link.onOpen}
                  >
                    <Icon name="link" size={16} />
                    {link.text}
                  </button>
                )}
              </span>
            )}
            <Link className="chain__node" to={artistPath(artist)}>
              <Cover name={artist.displayName} image={imageOf(artist)} round />
              <span className="chain__name">
                <bdi>{artist.displayName}</bdi>
              </span>
            </Link>
          </li>
        );
      })}
    </ol>
  );
}

/** Overlapping portraits (a group of artists at a glance). */
export function PortraitStack({
  artists,
  max = 5,
}: {
  artists: ArtistSummary[];
  max?: number;
}) {
  return (
    <span className="portrait-stack" aria-hidden="true">
      {artists.slice(0, max).map((artist, i) => (
        <Cover
          key={`${artist.name}-${i}`}
          name={artist.displayName}
          image={imageOf(artist)}
          round
        />
      ))}
    </span>
  );
}
