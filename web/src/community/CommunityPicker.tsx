/**
 * Find a campus or a city: a search pill, a country picker and (for campuses)
 * a demo filter, with results as compact cards. Fictional demo campuses are
 * badged "Demo" wherever they appear.
 */
import {
  useDeferredValue,
  useId,
  useMemo,
  useState,
  type CSSProperties,
} from 'react';

import {
  useCommunities,
  type Community,
  type CommunityKind,
} from '../api/community';
import {Icon} from '../components/Icon';
import {Cover} from '../components/Shelf';
import {ErrorState} from '../components/States';
import {useI18n} from '../i18n/i18n';

import {countryOptions} from './countries';
import {placeLabel} from './format';

/** Cards shown before "Show more". */
const PAGE = 12;

/** Demo campuses carry "(Demo)" in their name; the badge says it once. */
export function plainName(community: Community): string {
  return community.synthetic
    ? community.displayName.replace(/\s*\(demo\)\s*$/i, '')
    : community.displayName;
}

export function DemoBadge() {
  const {t} = useI18n();
  return <span className="demo-badge">{t('around.demo.badge')}</span>;
}

export function CommunityCard({
  community,
  onPick,
  note,
  index = 0,
}: {
  community: Community;
  onPick: (community: Community) => void;
  note?: string;
  /** Position in a staggered grid. */
  index?: number;
}) {
  const name = plainName(community);
  return (
    <li style={{'--i': index} as CSSProperties}>
      <button
        type="button"
        className="community-card"
        onClick={() => onPick(community)}
      >
        <Cover name={community.shortName || name} />
        <span className="community-card__text">
          <span className="community-card__name">
            <bdi>{name}</bdi>
          </span>
          <span className="community-card__place">
            <bdi>{note ?? placeLabel(community)}</bdi>
          </span>
        </span>
        {community.synthetic && <DemoBadge />}
      </button>
    </li>
  );
}

export function CardSkeletons({count = 6}: {count?: number}) {
  const {t} = useI18n();
  return (
    <div role="status" className="community-grid">
      <span className="visually-hidden">{t('state.loading')}</span>
      {Array.from({length: count}, (_, i) => (
        <div key={i} className="community-card" aria-hidden="true">
          <span className="skeleton community-card__skel-cover" />
          <span className="community-card__text">
            <span
              className="skeleton community-card__skel-line"
              style={{inlineSize: `${55 + ((i * 17) % 35)}%`}}
            />
            <span className="skeleton community-card__skel-line community-card__skel-line--short" />
          </span>
        </div>
      ))}
    </div>
  );
}

export function CommunityPicker({
  kind,
  onPick,
  exclude,
  label,
  compact = false,
}: {
  kind: CommunityKind;
  onPick: (community: Community) => void;
  /** A community not to offer (the one being compared against). */
  exclude?: string;
  label?: string;
  /** Fewer cards and no demo filter (inside another section). */
  compact?: boolean;
}) {
  const {t, locale} = useI18n();
  const id = useId();
  const [query, setQuery] = useState('');
  const [country, setCountry] = useState('');
  const [demo, setDemo] = useState(false);
  const [shown, setShown] = useState(compact ? 6 : PAGE);
  const deferred = useDeferredValue(query.trim());
  const results = useCommunities(deferred, kind, country, demo);
  const countries = useMemo(() => countryOptions(locale), [locale]);
  const items = (results.data?.communities ?? []).filter(
    c => c.name !== exclude,
  );
  const searchLabel = label ?? t(`around.search.${kind}`);
  const stale = results.isPlaceholderData;

  return (
    <div className="community-picker">
      <div className="community-picker__controls">
        <label className="search-pill" htmlFor={`${id}-q`}>
          <Icon name="search" />
          <input
            id={`${id}-q`}
            type="search"
            value={query}
            placeholder={searchLabel}
            aria-label={searchLabel}
            aria-controls={`${id}-results`}
            autoComplete="off"
            enterKeyHint="search"
            onChange={event => {
              setQuery(event.target.value);
              setShown(compact ? 6 : PAGE);
            }}
          />
        </label>
        <div className="community-picker__filters">
          <span className="select-pill">
            <Icon name="place" />
            <label className="visually-hidden" htmlFor={`${id}-country`}>
              {t('around.country')}
            </label>
            <select
              id={`${id}-country`}
              value={country}
              onChange={event => {
                setCountry(event.target.value);
                setShown(compact ? 6 : PAGE);
              }}
            >
              <option value="">{t('around.country.all')}</option>
              {countries.map(c => (
                <option key={c.code} value={c.code}>
                  {c.name}
                </option>
              ))}
            </select>
          </span>
          {kind === 'CAMPUS' && !compact && (
            <button
              type="button"
              className="chip"
              aria-pressed={demo}
              onClick={() => setDemo(value => !value)}
            >
              <Icon name={demo ? 'check' : 'school'} />
              {t('around.demo.only')}
            </button>
          )}
        </div>
      </div>
      {demo && (
        <p className="banner community-picker__demo" role="note">
          <Icon name="info" />
          <span>{t('around.demo.notice')}</span>
        </p>
      )}
      <p className="visually-hidden" role="status">
        {results.isSuccess && t('around.pick.results', {count: items.length})}
      </p>
      {results.isError ? (
        <ErrorState
          error={results.error}
          onRetry={() => void results.refetch()}
        />
      ) : results.isPending ? (
        <CardSkeletons count={compact ? 3 : 6} />
      ) : items.length === 0 ? (
        <div className="community-empty">
          <Icon name={kind === 'CAMPUS' ? 'school' : 'city'} size={32} />
          <p className="community-empty__title">
            {deferred
              ? t('around.pick.empty', {query: deferred})
              : t('around.pick.emptyCountry')}
          </p>
          <p className="muted">{t('around.pick.emptyBody')}</p>
        </div>
      ) : (
        <>
          <ul
            className="community-grid stagger"
            id={`${id}-results`}
            data-stale={stale || undefined}
          >
            {items.slice(0, shown).map((community, i) => (
              <CommunityCard
                key={community.name}
                index={i}
                community={community}
                onPick={onPick}
              />
            ))}
          </ul>
          {items.length > shown && (
            <button
              type="button"
              className="btn btn--outlined community-picker__more"
              onClick={() => setShown(n => n + PAGE)}
            >
              {t('around.pick.more', {count: items.length - shown})}
            </button>
          )}
        </>
      )}
    </div>
  );
}
