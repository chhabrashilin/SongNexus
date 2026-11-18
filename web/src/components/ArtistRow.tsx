/** A list row for an artist: photo or initial avatar, name, disambiguation, optional meta and action. */
import {useState, type CSSProperties, type ReactNode} from 'react';
import {Link} from 'react-router';

import {idOf, type ArtistSummary} from '../api/client';

import {useIntentPrefetch} from './useIntentPrefetch';

export function initialOf(name: string): string {
  const first = Array.from(name.trim())[0];
  return first ? first.toLocaleUpperCase() : '?';
}

/** A stable hue (0–359) for a name: the same artist always gets the same cover. */
export function hueOf(name: string): number {
  let hash = 0;
  for (const ch of name) hash = (hash * 31 + (ch.codePointAt(0) ?? 0)) >>> 0;
  return hash % 360;
}

/**
 * The artist's photo, when we have a freely licensed one (Wikimedia Commons,
 * ADR 0009). Tolerant of summaries stored before photos existed.
 */
export function imageOf(subject: object | null | undefined): string | null {
  return (subject as {imageUrl?: string | null} | null)?.imageUrl ?? null;
}

/**
 * A photo laid over generated art. The art (a gradient keyed to the name, with
 * the initial) is always underneath, so a slow or missing photo never leaves a
 * hole, and the photo fades in when it has loaded.
 */
export function CoverImage({
  src,
  eager = false,
}: {
  src: string;
  eager?: boolean;
}) {
  const [state, setState] = useState<'loading' | 'loaded' | 'failed'>(
    'loading',
  );
  if (state === 'failed') return null;
  return (
    <img
      className="cover__img"
      src={src}
      alt=""
      loading={eager ? 'eager' : 'lazy'}
      decoding="async"
      referrerPolicy="no-referrer"
      draggable={false}
      data-loaded={state === 'loaded' || undefined}
      // A cached image can finish before React attaches onLoad.
      ref={img => {
        if (img?.complete && img.naturalWidth > 0 && state === 'loading')
          setState('loaded');
      }}
      onLoad={() => setState('loaded')}
      onError={() => setState('failed')}
    />
  );
}

export function Avatar({
  name,
  large = false,
  image,
}: {
  name: string;
  large?: boolean;
  image?: string | null | undefined;
}) {
  return (
    <span
      className={
        large
          ? 'avatar avatar--lg cover cover--round'
          : 'avatar cover cover--round'
      }
      style={{'--hue': hueOf(name)} as CSSProperties}
      aria-hidden="true"
    >
      {initialOf(name)}
      {image && <CoverImage src={image} />}
    </span>
  );
}

export function artistPath(artist: Pick<ArtistSummary, 'name'>): string {
  return `/artist/${idOf(artist.name)}`;
}

interface Props {
  artist: ArtistSummary;
  subtitle?: ReactNode;
  meta?: ReactNode;
  action?: ReactNode;
  onClick?: () => void;
}

export function ArtistRow({artist, subtitle, meta, action, onClick}: Props) {
  const intent = useIntentPrefetch(idOf(artist.name));
  const body = (
    <>
      <Avatar name={artist.displayName} image={imageOf(artist)} />
      <span className="list-row__body">
        <span className="list-row__title">
          <bdi>{artist.displayName}</bdi>
        </span>
        {(subtitle ?? artist.disambiguation) && (
          <span className="list-row__subtitle">
            {subtitle ?? artist.disambiguation}
          </span>
        )}
      </span>
      {meta && <span className="list-row__meta">{meta}</span>}
    </>
  );
  return (
    <li className="row" style={{flexWrap: 'nowrap', minInlineSize: 0}}>
      {onClick ? (
        <button
          type="button"
          className="list-row"
          style={{flex: 1, minInlineSize: 0}}
          onClick={onClick}
        >
          {body}
        </button>
      ) : (
        <Link
          className="list-row"
          style={{flex: 1, minInlineSize: 0}}
          to={artistPath(artist)}
          {...intent}
        >
          {body}
        </Link>
      )}
      {action}
    </li>
  );
}
