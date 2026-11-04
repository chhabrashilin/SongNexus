/**
 * An artist's collaborations (US-16), by type, with evidence one tap away.
 *
 * Compact on the artist page; `full` on the collaborations page adds the
 * timeline, a year range and a chronological order. State lives in the URL
 * (`type`, `direction`, `from`, `to`, `order`, plus the genre filter), so a link
 * shows the same view.
 */
import {
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
} from 'react';
import {Link, useSearchParams} from 'react-router';

import {idOf, type Schemas} from '../api/client';
import {
  useCollaborations,
  type CollaborationType,
  type ProductionDirection,
} from '../api/queries';
import {isFiltered, useGenreSelection} from '../app/genreSelection';
import {ArtistRow} from '../components/ArtistRow';
import {ConnectionSheet} from '../components/ConnectionSheet';
import {GenreFilter} from '../components/Filters';
import {Icon} from '../components/Icon';
import {EmptyState, ErrorState, SkeletonRows} from '../components/States';
import {useI18n} from '../i18n/i18n';

import {Timeline, type YearRange} from './Timeline';

const TABS: CollaborationType[] = ['FEATURE', 'PRODUCTION', 'BAND', 'CREDIT'];
const DIRECTIONS: (ProductionDirection | null)[] = [
  null,
  'PRODUCED_FOR',
  'PRODUCED_BY',
  'CO_PRODUCED',
];
type Order = Schemas['CollaborationOrder'];

function year(value: string | null): number | null {
  return value && /^\d{4}$/.test(value) ? Number(value) : null;
}

/** The panel's view state, held in the URL. */
export function useCollaborationView() {
  const [search, setSearch] = useSearchParams();
  const view = useMemo(() => {
    const type = search.get('type') as CollaborationType | null;
    const direction = search.get('direction') as ProductionDirection | null;
    return {
      tab: type && TABS.includes(type) ? type : ('FEATURE' as const),
      direction: direction && DIRECTIONS.includes(direction) ? direction : null,
      range: {from: year(search.get('from')), to: year(search.get('to'))},
      order: (search.get('order') === 'FIRST_YEAR'
        ? 'FIRST_YEAR'
        : 'COUNT') as Order,
    };
  }, [search]);
  const update = (changes: Record<string, string | null>) =>
    setSearch(
      current => {
        const next = new URLSearchParams(current);
        for (const [key, value] of Object.entries(changes)) {
          if (value === null) next.delete(key);
          else next.set(key, value);
        }
        return next;
      },
      {replace: true},
    );
  return {view, update};
}

export function CollaborationsPanel({
  artistId,
  full = false,
}: {
  artistId: string;
  full?: boolean;
}) {
  const {t} = useI18n();
  const {view, update} = useCollaborationView();
  const {tab, direction, range, order} = view;
  const [pageToken, setPageToken] = useState('');
  const [items, setItems] = useState<Schemas['Collaboration'][]>([]);
  const [evidenceWith, setEvidenceWith] = useState<string | null>(null);
  const [genreFilter, setGenreFilter] = useGenreSelection();
  const [showFilters, setShowFilters] = useState(isFiltered(genreFilter));
  const activeDirection = tab === 'PRODUCTION' ? direction : null;
  const query = useCollaborations(
    artistId,
    tab,
    genreFilter,
    pageToken,
    activeDirection,
    {
      startYear: range.from,
      endYear: range.to,
      orderBy: order,
    },
  );
  const counts = query.data?.counts ?? {};
  const tabsId = useId();
  const tabRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const yearsKey = `${range.from}-${range.to}-${order}`;

  useEffect(() => {
    setItems([]);
    setPageToken('');
  }, [artistId, tab, genreFilter, activeDirection, yearsKey]);
  useEffect(() => {
    const page = query.data?.collaborations;
    if (page && !query.isPlaceholderData) {
      setItems(previous => (pageToken ? [...previous, ...page] : page));
    }
  }, [query.data, query.isPlaceholderData, pageToken]);

  function setTab(next: CollaborationType) {
    update({type: next === 'FEATURE' ? null : next});
  }

  function setRange(next: YearRange) {
    update({
      from: next.from === null ? null : String(next.from),
      to: next.to === null ? null : String(next.to),
    });
  }

  function onTabKey(event: KeyboardEvent, index: number) {
    const step =
      event.key === 'ArrowRight' ? 1 : event.key === 'ArrowLeft' ? -1 : 0;
    if (!step) return;
    const rtl = document.documentElement.dir === 'rtl';
    const next = (index + (rtl ? -step : step) + TABS.length) % TABS.length;
    setTab(TABS[next]!);
    tabRefs.current[next]?.focus();
  }

  const years = (query.data?.timeline ?? []).map(y => y.year);
  return (
    <section className="section">
      <div className="section__header">
        <h2>{t('collab.title')}</h2>
        <span className="muted" style={{font: 'var(--body-small)'}}>
          {t('collab.basis')}
        </span>
        <button
          type="button"
          className="btn btn--text"
          aria-expanded={showFilters}
          onClick={() => setShowFilters(open => !open)}
        >
          <Icon name="tune" />
          {t('collab.filter')}
        </button>
        {!full && (
          <Link
            className="btn btn--text"
            to={`/artist/${artistId}/collaborations`}
          >
            {t('collab.seeAll')}
          </Link>
        )}
      </div>
      {showFilters && (
        <div className="card stack">
          <GenreFilter selection={genreFilter} onChange={setGenreFilter} />
        </div>
      )}

      {full && query.data && (
        <div className="card stack">
          <Timeline
            timeline={query.data.timeline}
            undated={query.data.undated}
            range={range}
            onChange={setRange}
          />
          {years.length > 1 && (
            <div
              className="row"
              style={{flexWrap: 'wrap', alignItems: 'flex-end'}}
            >
              {(['from', 'to'] as const).map(end => (
                <label
                  key={end}
                  className="stack"
                  style={{gap: 'var(--space-1)'}}
                >
                  <span className="muted" style={{font: 'var(--label-medium)'}}>
                    {t(`collab.range.${end}`)}
                  </span>
                  <select
                    value={range[end] ?? ''}
                    onChange={event =>
                      setRange({
                        ...range,
                        [end]: event.target.value
                          ? Number(event.target.value)
                          : null,
                      })
                    }
                  >
                    <option value="">{t('collab.range.any')}</option>
                    {years.map(y => (
                      <option key={y} value={y}>
                        {y}
                      </option>
                    ))}
                  </select>
                </label>
              ))}
              {(range.from !== null || range.to !== null) && (
                <button
                  type="button"
                  className="btn btn--text"
                  onClick={() => setRange({from: null, to: null})}
                >
                  {t('collab.range.clear')}
                </button>
              )}
              <div
                className="chips"
                role="group"
                aria-label={t('collab.order')}
              >
                {(['COUNT', 'FIRST_YEAR'] as Order[]).map(option => (
                  <button
                    key={option}
                    type="button"
                    className="chip"
                    aria-pressed={order === option}
                    onClick={() =>
                      update({order: option === 'COUNT' ? null : option})
                    }
                  >
                    {t(`collab.order.${option}`)}
                  </button>
                ))}
              </div>
            </div>
          )}
          {(range.from !== null || range.to !== null) && (
            <p className="muted" style={{font: 'var(--body-small)'}}>
              {t('collab.range.undatedNote')}
            </p>
          )}
        </div>
      )}

      <div className="tabs" role="tablist" aria-label={t('collab.title')}>
        {TABS.map((type, index) => (
          <button
            key={type}
            ref={element => {
              tabRefs.current[index] = element;
            }}
            id={`${tabsId}-${type}`}
            type="button"
            role="tab"
            className="tab"
            aria-selected={tab === type}
            aria-controls={`${tabsId}-panel`}
            tabIndex={tab === type ? 0 : -1}
            onClick={() => setTab(type)}
            onKeyDown={event => onTabKey(event, index)}
          >
            {t(`collab.tab.${type}`)}
            <span className="badge">{counts[type] ?? 0}</span>
          </button>
        ))}
      </div>
      <div
        id={`${tabsId}-panel`}
        role="tabpanel"
        aria-labelledby={`${tabsId}-${tab}`}
      >
        {tab === 'PRODUCTION' && (
          <div
            className="chips"
            role="group"
            aria-label={t('collab.tab.PRODUCTION')}
          >
            {DIRECTIONS.map(option => (
              <button
                key={option ?? 'ALL'}
                type="button"
                className="chip"
                aria-pressed={direction === option}
                onClick={() => update({direction: option})}
              >
                {t(`collab.direction.${option ?? 'ALL'}`)}
              </button>
            ))}
          </div>
        )}
        {query.isError && (
          <ErrorState
            error={query.error}
            onRetry={() => void query.refetch()}
          />
        )}
        {query.isPending && items.length === 0 && <SkeletonRows />}
        {query.isSuccess && items.length === 0 && !query.isPlaceholderData && (
          <EmptyState title={t('collab.empty', {type: tab})} />
        )}
        <ul className="list">
          {items.map(item => (
            <ArtistRow
              key={item.artist.name}
              artist={item.artist}
              meta={
                <>
                  {t('collab.count', {count: item.count})}
                  {item.directions.length > 0 && (
                    <>
                      {' · '}
                      {item.directions
                        .map(d => t(`collab.direction.${d}`))
                        .join(', ')}
                    </>
                  )}
                  {item.firstYear !== null && item.lastYear !== null && (
                    <>
                      {' · '}
                      {item.firstYear === item.lastYear
                        ? t('collab.year', {year: item.firstYear})
                        : t('collab.years', {
                            first: item.firstYear,
                            last: item.lastYear,
                          })}
                    </>
                  )}
                </>
              }
              action={
                <button
                  type="button"
                  className="icon-btn"
                  onClick={() => setEvidenceWith(idOf(item.artist.name))}
                >
                  <Icon
                    name="chevron"
                    label={t('connection.showEvidence', {
                      name: item.artist.displayName,
                    })}
                  />
                </button>
              }
            />
          ))}
        </ul>
        {query.data?.nextPageToken && (
          <button
            type="button"
            className="btn btn--text"
            disabled={query.isFetching}
            onClick={() => setPageToken(query.data.nextPageToken)}
          >
            {t('action.showMore')}
          </button>
        )}
      </div>
      <ConnectionSheet
        a={evidenceWith ? artistId : null}
        b={evidenceWith}
        categories={[
          'FEATURES',
          'PRODUCERS',
          'CONTRIBUTIONS',
          'SAMPLES',
          'BANDS',
          'ENGINEERING',
        ]}
        onClose={() => setEvidenceWith(null)}
      />
    </section>
  );
}
