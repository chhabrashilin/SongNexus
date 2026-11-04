/** Label (R2-2, relationship graph): the roster by era and the releases in our data. */
import {useParams} from 'react-router';

import type {Schemas} from '../api/client';
import {useLabel} from '../api/queries';
import {usePageTitle} from '../app/Shell';
import {ArtistRow} from '../components/ArtistRow';
import {hostOf} from '../components/evidence';
import {Icon} from '../components/Icon';
import {EmptyState, ErrorState, Spinner} from '../components/States';
import {useI18n} from '../i18n/i18n';

/** Groups the roster by the decade of each artist's first release on the label. */
export function byEra(
  artists: Schemas['LabelArtist'][],
): [number | null, Schemas['LabelArtist'][]][] {
  const groups = new Map<number | null, Schemas['LabelArtist'][]>();
  for (const entry of artists) {
    const decade =
      entry.firstYear === null ? null : Math.floor(entry.firstYear / 10) * 10;
    groups.set(decade, [...(groups.get(decade) ?? []), entry]);
  }
  return [...groups.entries()].sort(([a], [b]) =>
    a === null ? 1 : b === null ? -1 : a - b,
  );
}

function years(first: number | null, last: number | null): string | null {
  if (first === null || last === null) return null;
  return first === last ? String(first) : `${first}–${last}`;
}

export default function LabelScreen() {
  const {t} = useI18n();
  const {id = ''} = useParams();
  const label = useLabel(id);
  usePageTitle(label.data?.displayName);

  if (label.isPending) return <Spinner />;
  if (label.isError)
    return (
      <ErrorState error={label.error} onRetry={() => void label.refetch()} />
    );
  const data = label.data;

  return (
    <article className="stack" style={{gap: 'var(--space-6)'}}>
      <header className="stack" style={{gap: 'var(--space-1)'}}>
        <h1>
          <bdi>{data.displayName}</bdi>
        </h1>
        <p className="muted">
          {[data.labelType, data.disambiguation].filter(Boolean).join(' · ') ||
            t('label.kind')}
        </p>
      </header>

      <section className="section">
        <div className="section__header">
          <h2>{t('label.roster')}</h2>
          <span className="muted" style={{font: 'var(--body-small)'}}>
            {t('label.basis')}
          </span>
        </div>
        {data.artists.length === 0 ? (
          <EmptyState title={t('label.noArtists')} />
        ) : (
          byEra(data.artists).map(([decade, entries]) => (
            <div
              key={decade ?? 'unknown'}
              className="stack"
              style={{gap: 'var(--space-1)'}}
            >
              <h3 className="muted" style={{font: 'var(--title-small)'}}>
                {decade === null
                  ? t('label.era.unknown')
                  : t('label.era', {decade})}
              </h3>
              <ul className="list">
                {entries.map(entry => (
                  <ArtistRow
                    key={entry.artist.name}
                    artist={entry.artist}
                    subtitle={[
                      t('label.releases', {count: entry.releaseCount}),
                      years(entry.firstYear, entry.lastYear),
                    ]
                      .filter(Boolean)
                      .join(' · ')}
                  />
                ))}
              </ul>
            </div>
          ))
        )}
      </section>

      {data.releases.length > 0 && (
        <section className="section">
          <h2>{t('label.releasesTitle')}</h2>
          <ul className="list">
            {data.releases.map(release => (
              <li key={release.release} className="list-row">
                <span className="avatar" aria-hidden="true">
                  <Icon name="album" />
                </span>
                <span className="list-row__body">
                  <span className="list-row__title">
                    <bdi>{release.displayName}</bdi>
                  </span>
                  <span className="list-row__subtitle">
                    {[
                      release.year,
                      release.artists.map(a => a.displayName).join(', '),
                      release.catalogNumbers.join(', '),
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

      {data.sources.length > 0 && (
        <section className="section">
          <h2>{t('artist.sources')}</h2>
          <ul className="list">
            {data.sources.map(source => (
              <li key={source.url}>
                <a href={source.url} target="_blank" rel="noopener noreferrer">
                  {t('connection.source', {host: hostOf(source.url)})}
                  <Icon name="external" size={14} />
                </a>
              </li>
            ))}
          </ul>
        </section>
      )}
    </article>
  );
}
