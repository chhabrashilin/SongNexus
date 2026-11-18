/**
 * Building blocks shared by the entity pages (artist, song, label,
 * collaborations): the immersive hero, big statistics, "Listen on YouTube
 * Music", the photo credit, "Show all" for long lists, designed not-found and
 * error states, and skeletons shaped like each page.
 */
import {useState, type CSSProperties, type ReactNode} from 'react';
import {Link} from 'react-router';

import {ApiError} from '../api/client';
import {CoverImage, hueOf} from '../components/ArtistRow';
import {Icon} from '../components/Icon';
import {Cover} from '../components/Shelf';
import {ErrorState} from '../components/States';
import {useI18n} from '../i18n/i18n';
import type {MessageId} from '../i18n/messages';

import {youTubeMusicSearch, type Photo} from './facts';

export type EntityKind = 'artist' | 'song' | 'label' | 'genre';

const MISSING_ICON = {
  artist: 'person',
  song: 'note',
  label: 'album',
  genre: 'spark',
} as const;

/** The first screenful of an entity page: art, overline, title, facts, stats and actions. */
export function EntityHero({
  kind,
  name,
  photo,
  overline,
  title,
  lead,
  meta,
  stats,
  actions,
  art,
  compact = false,
}: {
  kind: EntityKind;
  /** The name the art and color are generated from. */
  name: string;
  photo?: Photo | null;
  overline: ReactNode;
  /** Defaults to the name. */
  title?: ReactNode;
  lead?: ReactNode;
  /** Anything between the lead and the stats (genre chips, credits line). */
  meta?: ReactNode;
  stats?: ReactNode;
  actions?: ReactNode;
  /** Replaces the generated cover (the genre page's mosaic of its artists). */
  art?: ReactNode;
  /** A smaller hero (the collaborations page). */
  compact?: boolean;
}) {
  const round = kind === 'artist';
  return (
    <header
      className="entity-hero"
      data-kind={kind}
      data-compact={compact || undefined}
      data-photo={photo ? true : undefined}
      style={{'--hue': hueOf(name)} as CSSProperties}
    >
      {photo && (
        <div className="entity-hero__backdrop" aria-hidden="true">
          <CoverImage src={photo.thumbnailUrl || photo.url} eager />
        </div>
      )}
      <div className="entity-hero__art">
        <div className="entity-hero__glow" aria-hidden="true" />
        {art ?? <Cover name={name} round={round} image={photo?.url} eager />}
        {photo && <PhotoCredit photo={photo} />}
      </div>
      <div className="entity-hero__body">
        <p className="entity-hero__overline">{overline}</p>
        <h1 className="entity-hero__title">{title ?? <bdi>{name}</bdi>}</h1>
        {lead && <p className="entity-hero__lead">{lead}</p>}
        {meta}
        {stats}
        {actions && <div className="entity-hero__actions">{actions}</div>}
      </div>
    </header>
  );
}

/** Big numbers. Values are already formatted; a stat with no value is left out. */
export function Stats({
  items,
  label,
}: {
  items: {key: string; value: ReactNode; label: string}[];
  label: string;
}) {
  const shown = items.filter(item => item.value !== null && item.value !== '');
  if (shown.length === 0) return null;
  return (
    <dl className="stats entity-stats" aria-label={label}>
      {shown.map(item => (
        <div key={item.key} className="stat">
          <dt className="stat__label">{item.label}</dt>
          <dd className="stat__value">{item.value}</dd>
        </div>
      ))}
    </dl>
  );
}

/** "Listen on YouTube Music": a search there, in a new tab. */
export function ListenLink({
  query,
  primary = false,
}: {
  query: string;
  primary?: boolean;
}) {
  const {t} = useI18n();
  return (
    <a
      className={`btn ${primary ? 'btn--filled' : 'btn--tonal'} listen`}
      href={youTubeMusicSearch(query)}
      target="_blank"
      rel="noopener noreferrer"
    >
      <span className="listen__disc" aria-hidden="true">
        <Icon name="play" />
      </span>
      {t('entity.listen')}
      <span className="visually-hidden">{t('entity.newTab')}</span>
    </a>
  );
}

/** Author, license and file page, as the photo's license requires. */
export function PhotoCredit({photo}: {photo: Photo}) {
  const {t} = useI18n();
  return (
    <p className="photo-credit entity-hero__credit">
      {photo.author
        ? t('entity.photo.by', {author: photo.author})
        : t('entity.photo.unknownAuthor')}
      {photo.license && (
        <>
          {' · '}
          {photo.licenseUrl ? (
            <a
              href={photo.licenseUrl}
              target="_blank"
              rel="noopener noreferrer"
            >
              {photo.license}
            </a>
          ) : (
            photo.license
          )}
        </>
      )}
      {photo.pageUrl && (
        <>
          {' · '}
          <a href={photo.pageUrl} target="_blank" rel="noopener noreferrer">
            {t('entity.photo.file')}
          </a>
        </>
      )}
    </p>
  );
}

/** Long lists show a few and a "Show all" (v5 rule: no more than ~8 rows at once). */
export function useShowAll<T>(items: T[], limit: number) {
  const [all, setAll] = useState(false);
  const collapsible = items.length > limit + 1;
  return {
    visible: collapsible && !all ? items.slice(0, limit) : items,
    toggle: collapsible ? (
      <ShowAllButton
        expanded={all}
        count={items.length}
        onClick={() => setAll(value => !value)}
      />
    ) : null,
  };
}

export function ShowAllButton({
  expanded,
  count,
  onClick,
}: {
  expanded: boolean;
  count: number;
  onClick: () => void;
}) {
  const {t, formatNumber} = useI18n();
  return (
    <button
      type="button"
      className="btn btn--outlined btn--compact entity-show-all"
      aria-expanded={expanded}
      onClick={onClick}
    >
      {expanded
        ? t('entity.showLess')
        : t('entity.showAll', {count: formatNumber(count)})}
    </button>
  );
}

/** A titled section of an entity page. */
export function EntitySection({
  id,
  title,
  eyebrow,
  action,
  children,
  className,
}: {
  id: string;
  title: string;
  eyebrow?: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section
      className={className ? `entity-section ${className}` : 'entity-section'}
      aria-labelledby={id}
    >
      <div className="entity-section__header">
        <div className="entity-section__titles">
          {eyebrow && <p className="entity-section__eyebrow">{eyebrow}</p>}
          <h2 id={id}>{title}</h2>
        </div>
        {action && <div className="entity-section__action">{action}</div>}
      </div>
      {children}
    </section>
  );
}

/**
 * A failed load. Not found gets the page's own words and a way on; anything
 * else says what happened and offers a retry.
 */
export function EntityError({
  kind,
  error,
  onRetry,
}: {
  kind: EntityKind;
  error: unknown;
  onRetry: () => void;
}) {
  const {t} = useI18n();
  if (error instanceof ApiError && error.status === 'NOT_FOUND') {
    return (
      <div className="entity-missing">
        <span className="entity-missing__art" aria-hidden="true">
          <Icon name={MISSING_ICON[kind]} size={40} />
        </span>
        <h1 className="entity-missing__title">
          {t(`entity.notFound.${kind}` as MessageId)}
        </h1>
        <p className="entity-missing__body">{t('entity.notFound.body')}</p>
        <div className="entity-hero__actions">
          <Link className="btn btn--filled" to="/explore">
            <Icon name="explore" />
            {t('entity.notFound.explore')}
          </Link>
          <Link className="btn btn--tonal" to="/">
            {t('action.goHome')}
          </Link>
        </div>
      </div>
    );
  }
  return (
    <div className="entity-missing">
      <h1 className="visually-hidden">{t('state.error.title')}</h1>
      <ErrorState error={error} onRetry={onRetry} />
    </div>
  );
}

/** A skeleton shaped like the entity hero, then rows or covers. */
export function EntitySkeleton({
  kind,
  body = 'rows',
}: {
  kind: EntityKind;
  body?: 'rows' | 'covers';
}) {
  const {t} = useI18n();
  return (
    <div className="entity" role="status" aria-live="polite">
      <span className="visually-hidden">{t('state.loading')}</span>
      <div className="entity-hero" data-kind={kind} aria-hidden="true">
        <div className="entity-hero__art">
          <span
            className={`skeleton entity-skeleton__art${kind === 'artist' ? ' entity-skeleton__art--round' : ''}`}
          />
        </div>
        <div className="entity-hero__body">
          <span className="skeleton entity-skeleton__line" data-w="s" />
          <span className="skeleton entity-skeleton__title" />
          <span className="skeleton entity-skeleton__line" data-w="m" />
          <div className="stats entity-stats">
            {[0, 1, 2].map(i => (
              <span key={i} className="skeleton entity-skeleton__stat" />
            ))}
          </div>
          <div className="entity-hero__actions">
            {[0, 1, 2].map(i => (
              <span key={i} className="skeleton entity-skeleton__button" />
            ))}
          </div>
        </div>
      </div>
      <div className="entity-section" aria-hidden="true">
        <span className="skeleton entity-skeleton__line" data-w="s" />
        {body === 'covers' ? (
          <div className="entity-covers">
            {[0, 1, 2, 3, 4, 5].map(i => (
              <span key={i} className="stack">
                <span className="skeleton entity-skeleton__cover" />
                <span className="skeleton entity-skeleton__line" data-w="m" />
              </span>
            ))}
          </div>
        ) : (
          <div className="entity-rows">
            {[0, 1, 2, 3, 4, 5].map(i => (
              <span key={i} className="entity-skeleton__row">
                <span className="skeleton entity-skeleton__avatar" />
                <span
                  className="skeleton entity-skeleton__line"
                  data-w={i % 2 ? 'm' : 'l'}
                />
              </span>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
