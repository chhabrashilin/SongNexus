/** A list row for an artist: initial avatar, name, disambiguation, optional meta and action. */
import type {ReactNode} from 'react';
import {Link} from 'react-router';

import {idOf, type ArtistSummary} from '../api/client';

export function initialOf(name: string): string {
  const first = Array.from(name.trim())[0];
  return first ? first.toLocaleUpperCase() : '?';
}

export function Avatar({name, large = false}: {name: string; large?: boolean}) {
  return (
    <span className={large ? 'avatar avatar--lg' : 'avatar'} aria-hidden="true">
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
        >
          {body}
        </Link>
      )}
      {action}
    </li>
  );
}
