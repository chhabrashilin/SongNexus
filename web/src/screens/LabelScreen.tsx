/**
 * Label (R2-2, v5): a hero with the label's numbers, its releases per year,
 * the roster by era as covers, and the releases in our data.
 */
import {Fragment, type CSSProperties} from 'react';
import {Link, useParams} from 'react-router';

import {idOf, type Schemas} from '../api/client';
import {useLabel} from '../api/queries';
import {useAmbient} from '../app/ambient';
import {usePageTitle} from '../app/Shell';
import {artistPath, imageOf} from '../components/ArtistRow';
import {hostOf} from '../components/evidence';
import {Icon} from '../components/Icon';
import {Cover, CoverCard} from '../components/Shelf';
import {
  EntityError,
  EntityHero,
  EntitySection,
  EntitySkeleton,
  Stats,
  useShowAll,
} from '../entity/Entity';
import {spanOf, spanText} from '../entity/facts';
import {YearBars} from '../entity/YearBars';
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

/** The artist with the most releases on the label (ties: earliest first). */
export function flagship(
  artists: Schemas['LabelArtist'][],
): Schemas['LabelArtist'] | null {
  let best: Schemas['LabelArtist'] | null = null;
  for (const entry of artists) {
    if (
      !best ||
      entry.releaseCount > best.releaseCount ||
      (entry.releaseCount === best.releaseCount &&
        (entry.firstYear ?? Infinity) < (best.firstYear ?? Infinity))
    )
      best = entry;
  }
  return best;
}

function Era({
  decade,
  entries,
}: {
  decade: number | null;
  entries: Schemas['LabelArtist'][];
}) {
  const {t, formatNumber} = useI18n();
  const {visible, toggle} = useShowAll(entries, 12);
  return (
    <div className="entity-era">
      <h3 className="entity-era__title">
        {decade === null ? t('label.era.unknown') : t('label.era', {decade})}
        <span className="badge">{formatNumber(entries.length)}</span>
      </h3>
      <ul className="entity-covers stagger">
        {visible.map(entry => (
          <CoverCard
            key={entry.artist.name}
            to={artistPath(entry.artist)}
            title={entry.artist.displayName}
            subtitle={[
              t('label.releases', {count: entry.releaseCount}),
              spanText(spanOf([entry.firstYear, entry.lastYear])),
            ]
              .filter(Boolean)
              .join(' · ')}
            image={imageOf(entry.artist)}
            round
          />
        ))}
      </ul>
      {toggle}
    </div>
  );
}

function Releases({releases}: {releases: Schemas['LabelRelease'][]}) {
  const {t} = useI18n();
  const {visible, toggle} = useShowAll(releases, 8);
  return (
    <EntitySection id="label-releases" title={t('label.releasesTitle')}>
      <ul className="entity-releases stagger">
        {visible.map((release, index) => (
          <li
            key={release.release}
            className="entity-release"
            style={{'--i': index} as CSSProperties}
          >
            <Cover name={release.displayName} />
            <span className="entity-release__text">
              <span className="entity-release__title">
                <bdi>{release.displayName}</bdi>
              </span>
              <span className="entity-release__sub">
                {release.artists.map((artist, i) => (
                  <Fragment key={artist.name}>
                    {i > 0 && ', '}
                    <Link to={artistPath(artist)}>
                      <bdi>{artist.displayName}</bdi>
                    </Link>
                  </Fragment>
                ))}
              </span>
              {release.catalogNumbers.length > 0 && (
                <span className="entity-release__catalog">
                  {release.catalogNumbers.join(', ')}
                </span>
              )}
            </span>
            {release.year !== null && (
              <span className="entity-release__year">{release.year}</span>
            )}
          </li>
        ))}
      </ul>
      {toggle}
    </EntitySection>
  );
}

export default function LabelScreen() {
  const {t, formatNumber} = useI18n();
  const {id = ''} = useParams();
  const label = useLabel(id);
  usePageTitle(label.data?.displayName);
  useAmbient(label.data?.displayName ?? null);

  if (label.isPending) return <EntitySkeleton kind="label" body="covers" />;
  if (label.isError)
    return (
      <EntityError
        kind="label"
        error={label.error}
        onRetry={() => void label.refetch()}
      />
    );
  const data = label.data;
  const years = spanOf([
    ...data.releases.map(r => r.year),
    ...data.artists.flatMap(a => [a.firstYear, a.lastYear]),
  ]);
  const top = flagship(data.artists);

  return (
    <article className="entity">
      <EntityHero
        kind="label"
        name={data.displayName}
        overline={[t('label.kind'), data.labelType].filter(Boolean).join(' · ')}
        lead={data.disambiguation}
        stats={
          <Stats
            label={t('label.stat.label')}
            items={[
              {
                key: 'artists',
                value: formatNumber(data.artists.length),
                label: t('label.stat.artists', {count: data.artists.length}),
              },
              {
                key: 'releases',
                value: formatNumber(data.releases.length),
                label: t('label.stat.releases', {
                  count: data.releases.length,
                }),
              },
              {
                key: 'years',
                value: spanText(years),
                label: t('artist.stat.years'),
              },
            ]}
          />
        }
        actions={
          top && (
            <Link
              className="btn btn--filled"
              to={`/explore/${idOf(top.artist.name)}`}
            >
              <Icon name="explore" />
              {t('label.exploreTop', {name: top.artist.displayName})}
            </Link>
          )
        }
      />

      <YearBars
        title={t('label.perYear')}
        years={data.releases.map(r => r.year)}
      />

      <EntitySection
        id="label-roster"
        title={t('label.roster')}
        eyebrow={t('label.basis')}
      >
        {data.artists.length === 0 ? (
          <div className="entity-empty">
            <Icon name="people" />
            <p>{t('label.noArtists')}</p>
          </div>
        ) : (
          byEra(data.artists).map(([decade, entries]) => (
            <Era key={decade ?? 'unknown'} decade={decade} entries={entries} />
          ))
        )}
      </EntitySection>

      {data.releases.length > 0 && <Releases releases={data.releases} />}

      {data.sources.length > 0 && (
        <p className="entity-sources">
          {data.sources.map(source => (
            <a
              key={source.url}
              href={source.url}
              target="_blank"
              rel="noopener noreferrer"
            >
              {t('connection.source', {host: hostOf(source.url)})}
              <Icon name="external" size={14} />
            </a>
          ))}
        </p>
      )}
    </article>
  );
}
