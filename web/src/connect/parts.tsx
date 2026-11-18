/**
 * Pieces shared by the exploring tools (the Explore hub, find a path, compare
 * artists, compare songs): portraits, the "Listen on YouTube Music" pill, a
 * chain of portraits, the two-sided picker slot and the designed empty moment.
 */
import type {CSSProperties, ReactNode} from 'react';
import {Link} from 'react-router';

import {idOf, type ArtistSummary, type Schemas} from '../api/client';
import {imageOf} from '../components/ArtistRow';
import {Icon, type IconName} from '../components/Icon';
import {SearchBox} from '../components/SearchBox';
import {Cover, hueOf} from '../components/Shelf';
import {PhotoCredit} from '../entity/Entity';
import {useI18n} from '../i18n/i18n';

import {youTubeMusicUrl} from './mixtape';
import {BrandMark} from '../components/BrandMark';

/** "Listen on YouTube Music": opens a search there in a new tab. */
export function ListenLink({
  query,
  label,
  compact = false,
  iconOnly = false,
}: {
  query: string;
  /** The accessible name when the page has several ("Listen to X on …"). */
  label?: string;
  compact?: boolean;
  /** Just the red disc (dense rows); `label` is then required. */
  iconOnly?: boolean;
}) {
  const {t} = useI18n();
  return (
    <a
      className={
        iconOnly
          ? 'icon-btn cx-listen-disc'
          : `btn btn--tonal listen${compact ? ' btn--compact' : ''}`
      }
      href={youTubeMusicUrl(query)}
      target="_blank"
      rel="noopener noreferrer"
      aria-label={label}
    >
      <BrandMark provider="YOUTUBE_MUSIC" size={20} className="listen__disc" />
      {!iconOnly && t('connect.listen')}
    </a>
  );
}

/** A round portrait: the photo over the generated cover, optionally ringed for a side. */
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
    <span className="cx-portrait" data-size={size} data-side={side}>
      <Cover name={name} image={image} round eager={eager} />
    </span>
  );
}

/** Artists joined by a line, in order: a route at a glance. */
export function PortraitChain({
  artists,
  size = 's',
}: {
  artists: readonly ArtistSummary[];
  size?: 's' | 'm';
}) {
  return (
    <ol className="cx-chain" data-size={size}>
      {artists.map((artist, index) => (
        <li key={`${artist.name}-${index}`} className="cx-chain__item">
          <Link className="cx-chain__link" to={`/artist/${idOf(artist.name)}`}>
            <Portrait
              name={artist.displayName}
              image={imageOf(artist)}
              size={size}
            />
            <span className="cx-chain__name">
              <bdi>{artist.displayName}</bdi>
            </span>
          </Link>
        </li>
      ))}
    </ol>
  );
}

/** Sets `--hue` on a block from a name, so it takes its subject's color. */
export function hueStyle(name: string | null | undefined): CSSProperties {
  return {'--hue': name ? hueOf(name) : 350} as CSSProperties;
}

/**
 * One side of a two-sided screen: a large portrait (or an empty ring), the
 * name, and a picker under it. The picker's accessible name is `label`
 * (e2e tests use "From" and "To").
 */
export function ArtistSlot({
  label,
  caption,
  artist,
  side,
  loading = false,
  onPick,
}: {
  label: string;
  /** Shown above the name ("Start here"). */
  caption: string;
  artist:
    | {
        name: string;
        displayName: string;
        imageUrl?: string | null;
        /** Author and license of the photo (GetArtist), shown under it. */
        image?: Schemas['ArtistImage'] | null;
      }
    | undefined;
  side: 'a' | 'b';
  loading?: boolean;
  onPick: (id: string) => void;
}) {
  const {t} = useI18n();
  return (
    <div
      className="cx-slot"
      data-side={side}
      data-empty={!artist || undefined}
      style={hueStyle(artist?.displayName)}
    >
      {artist ? (
        <span className="cx-slot__art">
          <Portrait
            name={artist.displayName}
            image={imageOf(artist)}
            side={side}
            size="xl"
            eager
          />
        </span>
      ) : (
        <span
          className={loading ? 'cx-slot__ring skeleton' : 'cx-slot__ring'}
          aria-hidden="true"
        >
          {!loading && <Icon name="person" />}
        </span>
      )}
      <p className="cx-slot__caption">{caption}</p>
      <p className="cx-slot__name">
        {artist ? (
          <Link to={`/artist/${idOf(artist.name)}`}>
            <bdi>{artist.displayName}</bdi>
          </Link>
        ) : loading ? (
          <span className="skeleton cx-slot__name-skeleton" />
        ) : (
          t('path.pick.empty')
        )}
      </p>
      {artist?.image && imageOf(artist) && (
        <div className="cx-slot__credit">
          <PhotoCredit photo={artist.image} />
        </div>
      )}
      <div className="cx-slot__search">
        <SearchBox
          key={artist?.name ?? 'empty'}
          label={label}
          placeholder={artist ? t('connect.change') : t('path.pick.empty')}
          types={['ARTIST']}
          clearOnPick={false}
          onPick={result => onPick(idOf(result.name))}
        />
      </div>
    </div>
  );
}

type RecordingLike = Pick<
  Schemas['RecordingSummary'],
  'name' | 'displayName' | 'artists'
>;

/** A song's cover: its generated art with the lead artist's portrait set into it. */
export function SongCover({
  song,
  size = 'm',
  icon,
}: {
  song: {
    displayName: string;
    artists: readonly {displayName: string; imageUrl?: string | null}[];
  };
  size?: 's' | 'm' | 'xl';
  /** Shown instead of the title's initial. */
  icon?: IconName;
}) {
  const lead = song.artists[0];
  return (
    <span className="cx-song-cover" data-size={size} aria-hidden="true">
      <Cover name={song.displayName} icon={icon} />
      {lead && (
        <span className="cx-song-cover__artist">
          <Cover
            name={lead.displayName}
            image={imageOf(lead)}
            round
            eager={size === 'xl'}
          />
        </span>
      )}
    </span>
  );
}

/** The song side of a comparison: cover, title, artists, and a picker. */
export function SongSlot({
  label,
  song,
  side,
  loading = false,
  onPick,
}: {
  label: string;
  song: RecordingLike | undefined;
  side: 'a' | 'b';
  loading?: boolean;
  onPick: (id: string) => void;
}) {
  const {t} = useI18n();
  return (
    <div
      className="cx-slot"
      data-side={side}
      data-empty={!song || undefined}
      style={hueStyle(song?.displayName)}
    >
      {song ? (
        <span className="cx-slot__art" data-side={side}>
          <SongCover song={song} size="xl" />
        </span>
      ) : (
        <span
          className={
            loading
              ? 'cx-slot__ring cx-slot__ring--square skeleton'
              : 'cx-slot__ring cx-slot__ring--square'
          }
          aria-hidden="true"
        >
          {!loading && <Icon name="note" />}
        </span>
      )}
      <p className="cx-slot__caption">{label}</p>
      <p className="cx-slot__name">
        {song ? (
          <Link to={`/song/${idOf(song.name)}`}>
            <bdi>{song.displayName}</bdi>
          </Link>
        ) : loading ? (
          <span className="skeleton cx-slot__name-skeleton" />
        ) : (
          t('songCompare.pick.empty')
        )}
      </p>
      {song && song.artists.length > 0 && (
        <p className="cx-slot__sub">
          <bdi>{song.artists.map(a => a.displayName).join(', ')}</bdi>
        </p>
      )}
      <div className="cx-slot__search">
        <SearchBox
          key={song?.name ?? 'empty'}
          label={label}
          placeholder={song ? t('connect.change') : t('songCompare.pick.empty')}
          types={['RECORDING']}
          clearOnPick={false}
          onPick={result => onPick(idOf(result.name))}
        />
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
  art,
}: {
  icon: IconName;
  title: string;
  body?: string;
  children?: ReactNode;
  /** Replaces the icon (portraits, for instance). */
  art?: ReactNode;
}) {
  return (
    <div className="cx-moment">
      {art ?? (
        <span className="cx-moment__icon" aria-hidden="true">
          <Icon name={icon} />
        </span>
      )}
      <p className="cx-moment__title">{title}</p>
      {body && <p className="cx-moment__body">{body}</p>}
      {children && <div className="cx-moment__actions">{children}</div>}
    </div>
  );
}

/** The page top shared by the tools: an overline, the one h1, a lead. */
export function ToolHero({
  overline,
  icon,
  title,
  lead,
  children,
}: {
  overline: string;
  icon: IconName;
  title: string;
  lead: string;
  children?: ReactNode;
}) {
  return (
    <header className="cx-hero">
      <p className="cx-hero__overline">
        <Icon name={icon} />
        {overline}
      </p>
      <h1 className="cx-hero__title">{title}</h1>
      <p className="cx-hero__lead">{lead}</p>
      {children}
    </header>
  );
}
