/**
 * Pieces shared by the exploring screens (the web, find a path, compare):
 * portraits, "Listen on YouTube Music", a chain of portraits, the head-to-head
 * header and the designed "not in our data yet" state.
 */
import type {CSSProperties, ReactNode} from 'react';
import {Link} from 'react-router';

import {idOf, type ArtistSummary} from '../api/client';
import {imageOf} from '../components/ArtistRow';
import {Icon} from '../components/Icon';
import {Cover, hueOf} from '../components/Shelf';
import {useI18n} from '../i18n/i18n';
import {BrandMark} from '../components/BrandMark';

/** A search on YouTube Music: we link out, we never claim playback. */
export function youTubeMusicUrl(query: string): string {
  return `https://music.youtube.com/search?q=${encodeURIComponent(query)}`;
}

/** "Listen on YouTube Music", opening a search there in a new tab. */
export function ListenLink({
  query,
  name,
  compact = false,
  primary = false,
}: {
  query: string;
  /** Who it is for, read to screen readers when a page has several. */
  name?: string;
  compact?: boolean;
  primary?: boolean;
}) {
  const {t} = useI18n();
  return (
    <a
      className={`btn ${primary ? 'btn--filled' : 'btn--tonal'} ${compact ? 'btn--compact ' : ''}listen`}
      href={youTubeMusicUrl(query)}
      target="_blank"
      rel="noopener noreferrer"
      aria-label={name ? t('explore.listenTo', {name}) : undefined}
    >
      <BrandMark provider="YOUTUBE_MUSIC" size={20} className="listen__disc" />
      {t('explore.listen')}
    </a>
  );
}

/**
 * A round portrait: the artist's photo over their generated cover. `side`
 * tints the ring with a data color when two artists are compared.
 */
export function Portrait({
  name,
  image,
  side,
  size = 'm',
  eager = false,
}: {
  name: string;
  image?: string | null;
  side?: 'a' | 'b';
  size?: 's' | 'm' | 'l' | 'xl';
  eager?: boolean;
}) {
  return (
    <span className="portrait" data-size={size} data-side={side}>
      <Cover name={name} image={image} round eager={eager} />
    </span>
  );
}

/** Artists joined by lines, in order (a path at a glance). */
export function PortraitChain({
  artists,
  link = true,
}: {
  artists: ArtistSummary[];
  link?: boolean;
}) {
  return (
    <ol className="chain">
      {artists.map((artist, index) => (
        <li key={`${artist.name}-${index}`} className="chain__item">
          {link ? (
            <Link className="chain__link" to={`/artist/${idOf(artist.name)}`}>
              <Portrait
                name={artist.displayName}
                image={imageOf(artist)}
                size="s"
              />
              <span className="chain__name">
                <bdi>{artist.displayName}</bdi>
              </span>
            </Link>
          ) : (
            <span className="chain__link">
              <Portrait
                name={artist.displayName}
                image={imageOf(artist)}
                size="s"
              />
              <span className="chain__name">
                <bdi>{artist.displayName}</bdi>
              </span>
            </span>
          )}
        </li>
      ))}
    </ol>
  );
}

/** Sets a hue for a block from a name (the subject's own color). */
export function hueStyle(name: string | null | undefined): CSSProperties {
  return {'--hue': name ? hueOf(name) : 350} as CSSProperties;
}

/**
 * The top of a two-sided screen: two portraits facing each other with a
 * medallion between them, each side with its own picker below the name.
 */
export function FaceOff({
  a,
  b,
  middle,
}: {
  a: ReactNode;
  b: ReactNode;
  middle: ReactNode;
}) {
  return (
    <div className="faceoff">
      <div className="faceoff__side" data-side="a">
        {a}
      </div>
      <div className="faceoff__middle">{middle}</div>
      <div className="faceoff__side" data-side="b">
        {b}
      </div>
    </div>
  );
}

/** A designed empty or "not in our data yet" moment, with what to do next. */
export function Moment({
  icon,
  title,
  body,
  children,
}: {
  icon: Parameters<typeof Icon>[0]['name'];
  title: string;
  body?: string;
  children?: ReactNode;
}) {
  return (
    <div className="moment">
      <span className="moment__icon" aria-hidden="true">
        <Icon name={icon} />
      </span>
      <p className="moment__title">{title}</p>
      {body && <p className="moment__body">{body}</p>}
      {children && <div className="moment__actions">{children}</div>}
    </div>
  );
}
