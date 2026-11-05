/** Artist page (S4): header, genres, actions, collaborations (US-16), labels, aliases, links, sources. */
import {useEffect} from 'react';
import {Link, useParams} from 'react-router';

import {idOf, type Schemas} from '../api/client';
import {useArtist, useDataSources} from '../api/queries';
import {rememberArtist} from '../app/recent';
import {usePageTitle} from '../app/Shell';
import {useBlock} from '../app/useBlock';
import {CollaborationsPanel} from '../collaborations/CollaborationsPanel';
import {ArtistRow, Avatar} from '../components/ArtistRow';
import {hostOf} from '../components/evidence';
import {Icon} from '../components/Icon';
import {ErrorState, Spinner} from '../components/States';
import {useI18n} from '../i18n/i18n';
import type {MessageId} from '../i18n/messages';

function typeLabel(type: string | null | undefined): MessageId {
  const known = ['Person', 'Group', 'Orchestra', 'Choir', 'Character'];
  return (
    type && known.includes(type) ? `artist.type.${type}` : 'artist.type.other'
  ) as MessageId;
}

/** Names the data sources behind an artist's genres (ADR 0005). */
function GenreSources({
  ids,
  sources,
}: {
  ids: string[];
  sources: Schemas['DataSource'][];
}) {
  const {t} = useI18n();
  const names = sources
    .filter(s => ids.includes(s.name))
    .map(s => s.displayName);
  if (names.length === 0) return null;
  return (
    <p
      className="muted"
      style={{font: 'var(--body-small)', inlineSize: '100%'}}
    >
      {t('artist.genreSources', {sources: names.join(', ')})}
    </p>
  );
}

export default function ArtistScreen() {
  const {t} = useI18n();
  const {id = ''} = useParams();
  const artist = useArtist(id);
  const sources = useDataSources();
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
            <GenreSources
              ids={a.genres.flatMap(g => g.sources)}
              sources={sources.data ?? []}
            />
          </div>
        ) : (
          <p className="muted">{t('artist.genresUnknown')}</p>
        )}
      </section>

      <CollaborationsPanel artistId={id} />

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

      {a.oftenPlayedWith.length > 0 && (
        <section className="section">
          <div className="section__header">
            <h2>{t('artist.oftenPlayedWith')}</h2>
            <span className="muted" style={{font: 'var(--body-small)'}}>
              {t('artist.oftenPlayedWith.basis')}
            </span>
          </div>
          <ul className="list">
            {a.oftenPlayedWith.map(entry => (
              <ArtistRow
                key={entry.artist.name}
                artist={entry.artist}
                meta={t('artist.oftenPlayedWith.rank', {rank: entry.rank})}
              />
            ))}
          </ul>
        </section>
      )}

      {a.labels.length > 0 && (
        <section className="section">
          <h2>{t('artist.labels')}</h2>
          <ul className="list">
            {a.labels.map(label => (
              <li key={label.label} className="list-row">
                <span className="avatar" aria-hidden="true">
                  <Icon name="album" />
                </span>
                <span className="list-row__body">
                  <Link
                    className="list-row__title"
                    to={`/label/${idOf(label.label)}`}
                  >
                    <bdi>{label.displayName}</bdi>
                  </Link>
                  <span className="list-row__subtitle">
                    {[
                      t('label.releases', {count: label.releaseCount}),
                      label.firstYear !== null && label.lastYear !== null
                        ? label.firstYear === label.lastYear
                          ? String(label.firstYear)
                          : `${label.firstYear}–${label.lastYear}`
                        : null,
                    ]
                      .filter(Boolean)
                      .join(' · ')}
                  </span>
                </span>
              </li>
            ))}
          </ul>
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
