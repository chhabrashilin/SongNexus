/** A list row for an artist: initial avatar, name, disambiguation, optional meta and action. */
import type {CSSProperties, ReactNode} from 'react';
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

export function Avatar({name, large = false}: {name: string; large?: boolean}) {
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
      <Avatar name={artist.displayName} />
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
