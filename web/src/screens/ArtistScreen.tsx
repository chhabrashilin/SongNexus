/** Artist page (S4): header, genres, actions, Collaborations tabs (US-16), aliases, links, sources. */
import {useEffect, useId, useRef, useState, type KeyboardEvent} from 'react';
import {Link, useParams} from 'react-router';

import {idOf, type Schemas} from '../api/client';
import {
  useArtist,
  useCollaborations,
  type CollaborationType,
} from '../api/queries';
import {rememberArtist} from '../app/recent';
import {usePageTitle} from '../app/Shell';
import {useBlock} from '../app/useBlock';
import {ArtistRow, Avatar} from '../components/ArtistRow';
import {ConnectionSheet} from '../components/ConnectionSheet';
import {hostOf} from '../components/evidence';
import {Icon} from '../components/Icon';
import {
  EmptyState,
  ErrorState,
  SkeletonRows,
  Spinner,
} from '../components/States';
import {useI18n} from '../i18n/i18n';
import type {MessageId} from '../i18n/messages';

const TABS: CollaborationType[] = ['FEATURE', 'PRODUCTION', 'BAND', 'CREDIT'];

function typeLabel(type: string | null | undefined): MessageId {
  const known = ['Person', 'Group', 'Orchestra', 'Choir', 'Character'];
  return (
    type && known.includes(type) ? `artist.type.${type}` : 'artist.type.other'
  ) as MessageId;
}

function Collaborations({
  artistId,
  counts,
}: {
  artistId: string;
  counts: Partial<Record<CollaborationType, number>>;
}) {
  const {t} = useI18n();
  const [tab, setTab] = useState<CollaborationType>('FEATURE');
  const [pageToken, setPageToken] = useState('');
  const [items, setItems] = useState<Schemas['Collaboration'][]>([]);
  const [evidenceWith, setEvidenceWith] = useState<string | null>(null);
  const query = useCollaborations(artistId, tab, pageToken);
  const tabsId = useId();
  const tabRefs = useRef<(HTMLButtonElement | null)[]>([]);

  useEffect(() => {
    setItems([]);
    setPageToken('');
  }, [artistId, tab]);
  useEffect(() => {
    const page = query.data?.collaborations;
    if (page && !query.isPlaceholderData) {
      setItems(previous => (pageToken ? [...previous, ...page] : page));
    }
  }, [query.data, query.isPlaceholderData, pageToken]);

  function onTabKey(event: KeyboardEvent, index: number) {
    const step =
      event.key === 'ArrowRight' ? 1 : event.key === 'ArrowLeft' ? -1 : 0;
    if (!step) return;
    const rtl = document.documentElement.dir === 'rtl';
    const next = (index + (rtl ? -step : step) + TABS.length) % TABS.length;
    setTab(TABS[next]!);
    tabRefs.current[next]?.focus();
  }

  return (
    <section className="section">
      <div className="section__header">
        <h2>{t('collab.title')}</h2>
        <span className="muted" style={{font: 'var(--body-small)'}}>
          {t('collab.basis')}
        </span>
      </div>
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

export default function ArtistScreen() {
  const {t} = useI18n();
  const {id = ''} = useParams();
  const artist = useArtist(id);
  const counts = useCollaborations(id, 'FEATURE').data?.counts ?? {};
  const block = useBlock(artist.data);
  usePageTitle(artist.data?.displayName);

  useEffect(() => {
    if (artist.data) rememberArtist(artist.data);
  }, [artist.data]);

  if (artist.isPending) return <Spinner />;
  if (artist.isError)
    return (
      <ErrorState error={artist.error} onRetry={() => void artist.refetch()} />
    );
  const a = artist.data;

  return (
    <article className="stack" style={{gap: 'var(--space-6)'}}>
      <header className="stack">
        <div
          className="row"
          style={{gap: 'var(--space-4)', flexWrap: 'nowrap'}}
        >
          <Avatar name={a.displayName} large />
          <div className="stack" style={{gap: 'var(--space-1)'}}>
            <h1>
              <bdi>{a.displayName}</bdi>
            </h1>
            <p className="muted">
              {[
                t(typeLabel(a.artistType)),
                a.country,
                a.disambiguation,
                t('artist.connections', {count: a.connectionCount}),
              ]
                .filter(Boolean)
                .join(' · ')}
            </p>
          </div>
        </div>
        {a.detailLevel === 'stub' && (
          <p className="banner">{t('artist.detail.stub')}</p>
        )}
        {block.blocked && <p className="banner">{t('artist.blocked')}</p>}
        <div className="row">
          <Link className="btn btn--filled" to={`/explore/${id}`}>
            <Icon name="explore" />
            {t('artist.explore')}
          </Link>
          <Link className="btn btn--tonal" to={`/six-degrees?from=${id}`}>
            <Icon name="route" />
            {t('artist.findPath')}
          </Link>
          <Link className="btn btn--tonal" to={`/compare?a=${id}`}>
            <Icon name="compare" />
            {t('artist.compare')}
          </Link>
          <button
            type="button"
            className="btn btn--text"
            disabled={block.busy}
            onClick={() => void block.toggle()}
          >
            <Icon name="block" />
            {block.blocked ? t('artist.unblock') : t('artist.block')}
          </button>
        </div>
      </header>

      <section className="section">
        <h2>{t('artist.genres')}</h2>
        {a.genres.length ? (
          <div className="chips">
            {a.genres.map(g => (
              <span key={g.genre} className="chip" style={{cursor: 'default'}}>
                {g.displayName}
              </span>
            ))}
          </div>
        ) : (
          <p className="muted">{t('artist.genresUnknown')}</p>
        )}
      </section>

      <Collaborations artistId={id} counts={counts} />

      {a.aliases.length > 0 && (
        <section className="section">
          <h2>{t('artist.aka')}</h2>
          <p>
            {a.aliases.map((alias, i) => (
              <span key={`${alias.displayName}-${i}`}>
                {i > 0 && ', '}
                <bdi lang={alias.locale ?? undefined}>{alias.displayName}</bdi>
              </span>
            ))}
          </p>
        </section>
      )}

      {(a.links.length > 0 || a.sources.length > 0) && (
        <section className="section">
          <h2>{t('artist.links')}</h2>
          <ul className="list">
            {[...a.links.map(l => l.url), ...a.sources.map(s => s.url)].map(
              url => (
                <li key={url}>
                  <a
                    className="list-row"
                    href={url}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    <span className="list-row__body">{hostOf(url)}</span>
                    <Icon name="external" size={18} />
                  </a>
                </li>
              ),
            )}
          </ul>
        </section>
      )}
    </article>
  );
}
