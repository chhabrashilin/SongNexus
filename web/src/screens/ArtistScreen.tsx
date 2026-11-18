/**
 * Artist page (S4, v5): an immersive hero (photo or generated cover, name,
 * key numbers, listen and explore), then collaborations, who listeners play
 * alongside, labels, other names and links grouped by what they are for.
 */
import {useEffect, useMemo, type CSSProperties} from 'react';
import {Link, useParams} from 'react-router';

import {idOf, type Schemas} from '../api/client';
import {useArtist, useCollaborations, useDataSources} from '../api/queries';
import {useAmbient} from '../app/ambient';
import {NO_GENRE_FILTER} from '../app/genreSelection';
import {rememberArtist} from '../app/recent';
import {usePageTitle} from '../app/Shell';
import {useBlock} from '../app/useBlock';
import {CollaborationsPanel} from '../collaborations/CollaborationsPanel';
import {artistPath, imageOf} from '../components/ArtistRow';
import {Icon} from '../components/Icon';
import {Cover, CoverCard, Shelf} from '../components/Shelf';
import {
  EntityError,
  EntityHero,
  EntitySection,
  EntitySkeleton,
  ListenLink,
  Stats,
  useShowAll,
} from '../entity/Entity';
import {
  countryName,
  listenersOf,
  photoOf,
  spanOf,
  spanText,
  yearOf,
} from '../entity/facts';
import {groupLinks, type LinkGroup} from '../entity/links';
import {ArtistRecommendations} from '../entity/Recommendations';
import {useI18n} from '../i18n/i18n';
import type {MessageId} from '../i18n/messages';
import {ShareButton} from '../social/ShareSheet';

const KNOWN_TYPES = ['Person', 'Group', 'Orchestra', 'Choir', 'Character'];

function typeLabel(type: string | null | undefined): MessageId {
  return (
    type && KNOWN_TYPES.includes(type)
      ? `artist.type.${type}`
      : 'artist.type.other'
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
    <p className="entity-hero__note">
      {t('artist.genreSources', {sources: names.join(', ')})}
    </p>
  );
}

function Genres({artist}: {artist: Schemas['Artist']}) {
  const {t} = useI18n();
  const sources = useDataSources();
  if (artist.genres.length === 0)
    return <p className="entity-hero__note">{t('artist.genresUnknown')}</p>;
  return (
    <div className="entity-hero__genres">
      <ul className="chips" aria-label={t('artist.genres')}>
        {artist.genres.slice(0, 6).map(g => (
          <li key={g.genre}>
            <Link className="chip" to={`/genre/${idOf(g.genre)}`}>
              <bdi>{g.displayName}</bdi>
            </Link>
          </li>
        ))}
      </ul>
      <GenreSources
        ids={artist.genres.flatMap(g => g.sources)}
        sources={sources.data ?? []}
      />
    </div>
  );
}

function Labels({labels}: {labels: Schemas['ArtistLabel'][]}) {
  const {t} = useI18n();
  const {visible, toggle} = useShowAll(labels, 8);
  return (
    <EntitySection
      id="artist-labels"
      title={t('artist.labels')}
      eyebrow={t('label.basis')}
    >
      <ul className="entity-cards stagger">
        {visible.map((label, index) => (
          <li key={label.label} style={{'--i': index} as CSSProperties}>
            <Link className="entity-card" to={`/label/${idOf(label.label)}`}>
              <Cover name={label.displayName} />
              <span className="entity-card__text">
                <span className="entity-card__title">
                  <bdi>{label.displayName}</bdi>
                </span>
                <span className="entity-card__sub">
                  {[
                    t('label.releases', {count: label.releaseCount}),
                    spanText(spanOf([label.firstYear, label.lastYear])),
                  ]
                    .filter(Boolean)
                    .join(' · ')}
                </span>
              </span>
            </Link>
          </li>
        ))}
      </ul>
      {toggle}
    </EntitySection>
  );
}

function Aliases({aliases}: {aliases: Schemas['Alias'][]}) {
  const {t} = useI18n();
  const legal = aliases.find(a => a.aliasType === 'legal_name');
  const others = aliases.filter(a => a !== legal);
  const {visible, toggle} = useShowAll(others, 8);
  return (
    <div className="entity-about__block">
      <h3 className="entity-about__title">{t('artist.aka')}</h3>
      {legal && (
        <p className="entity-about__legal">
          <span className="muted">{t('artist.legalName')}</span>{' '}
          <bdi lang={legal.locale ?? undefined}>{legal.displayName}</bdi>
        </p>
      )}
      {visible.length > 0 && (
        <ul className="chips">
          {visible.map((alias, i) => (
            <li key={`${alias.displayName}-${i}`} className="chip entity-chip">
              <bdi lang={alias.locale ?? undefined}>{alias.displayName}</bdi>
            </li>
          ))}
        </ul>
      )}
      {toggle}
    </div>
  );
}

const GROUP_ICON: Record<LinkGroup, 'play' | 'home' | 'people' | 'library'> = {
  listen: 'play',
  official: 'home',
  social: 'people',
  reference: 'library',
};

function Links({artist}: {artist: Schemas['Artist']}) {
  const {t} = useI18n();
  const groups = useMemo(
    () => groupLinks(artist.links, artist.sources),
    [artist.links, artist.sources],
  );
  if (groups.length === 0) return null;
  return (
    <div className="entity-about__block">
      <h3 className="entity-about__title">{t('artist.links')}</h3>
      {groups.map(([group, links]) => (
        <div key={group} className="entity-links">
          <h4 className="entity-links__title">
            <Icon name={GROUP_ICON[group]} size={16} />
            {t(`artist.links.${group}`)}
          </h4>
          <ul className="entity-links__list">
            {links.map(link => (
              <li key={link.url}>
                <a
                  className="entity-link"
                  href={link.url}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  {link.name}
                  <Icon name="external" size={14} />
                  <span className="visually-hidden">{t('entity.newTab')}</span>
                </a>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}

function OftenPlayedWith({entries}: {entries: Schemas['CoListener'][]}) {
  const {t} = useI18n();
  return (
    <Shelf
      eyebrow={t('artist.oftenPlayedWith.basis')}
      title={t('artist.oftenPlayedWith')}
    >
      {entries.map(entry => (
        <CoverCard
          key={entry.artist.name}
          to={artistPath(entry.artist)}
          title={entry.artist.displayName}
          subtitle={entry.artist.disambiguation || t('search.type.ARTIST')}
          image={imageOf(entry.artist)}
          badge={t('artist.oftenPlayedWith.rank', {rank: entry.rank})}
          round
        />
      ))}
    </Shelf>
  );
}

function useArtistStats(id: string, artist: Schemas['Artist'] | undefined) {
  const {t, formatNumber} = useI18n();
  const collaborations = useCollaborations(id, 'FEATURE', NO_GENRE_FILTER);
  const data = collaborations.data;
  if (!artist) return [];
  const counts = Object.values(data?.counts ?? {}).filter(
    (n): n is number => typeof n === 'number',
  );
  // The largest kind is a floor on distinct collaborators (one person can be in several kinds).
  const collaborators = counts.length ? Math.max(...counts) : null;
  const years = spanOf([
    ...(data?.timeline ?? []).map(y => y.year),
    ...artist.labels.flatMap(l => [l.firstYear, l.lastYear]),
  ]);
  const listeners = listenersOf(artist);
  return [
    {
      key: 'connections',
      value: formatNumber(artist.connectionCount),
      label: t('artist.stat.connections', {count: artist.connectionCount}),
    },
    {
      key: 'collaborators',
      value: collaborators === null ? null : formatNumber(collaborators),
      label: t('artist.stat.collaborators', {count: collaborators ?? 0}),
    },
    {
      key: 'labels',
      value: artist.labels.length ? formatNumber(artist.labels.length) : null,
      label: t('artist.stat.labels', {count: artist.labels.length}),
    },
    {
      key: 'listeners',
      value:
        listeners === null
          ? null
          : formatNumber(listeners, {
              notation: 'compact',
              maximumFractionDigits: 1,
            }),
      label: t('artist.stat.listeners', {count: listeners ?? 0}),
    },
    {
      key: 'years',
      value: spanText(years),
      label: t('artist.stat.years'),
    },
  ];
}

export default function ArtistScreen() {
  const {t, locale} = useI18n();
  const {id = ''} = useParams();
  const artist = useArtist(id);
  const block = useBlock(artist.data);
  const stats = useArtistStats(id, artist.data);
  usePageTitle(artist.data?.displayName);
  useAmbient(artist.data?.displayName ?? null);

  useEffect(() => {
    if (artist.data) rememberArtist(artist.data);
  }, [artist.data]);

  if (artist.isPending) return <EntitySkeleton kind="artist" />;
  if (artist.isError)
    return (
      <EntityError
        kind="artist"
        error={artist.error}
        onRetry={() => void artist.refetch()}
      />
    );
  const a = artist.data;
  const born = yearOf(a.beginDate);
  const overline = [
    t(typeLabel(a.artistType)),
    countryName(a.country, locale),
    born !== null
      ? t(a.artistType === 'Person' ? 'artist.born' : 'artist.formed', {
          year: born,
        })
      : null,
  ]
    .filter(Boolean)
    .join(' · ');

  return (
    <article className="entity">
      <EntityHero
        kind="artist"
        name={a.displayName}
        photo={photoOf(a)}
        overline={overline}
        lead={a.disambiguation}
        meta={<Genres artist={a} />}
        stats={<Stats items={stats} label={t('artist.stat.label')} />}
        actions={
          <>
            <Link className="btn btn--filled" to={`/explore/${id}`}>
              <Icon name="explore" />
              {t('artist.explore')}
            </Link>
            <ListenLink query={a.displayName} />
            <Link className="btn btn--tonal" to={`/six-degrees?from=${id}`}>
              <Icon name="route" />
              {t('artist.findPath')}
            </Link>
            <Link className="btn btn--tonal" to={`/compare?a=${id}`}>
              <Icon name="compare" />
              {t('artist.compare')}
            </Link>
            <ShareButton
              kind="ARTIST"
              subjects={[a.name]}
              title={a.displayName}
            />
            <button
              type="button"
              className="btn btn--text"
              disabled={block.busy}
              onClick={() => void block.toggle()}
            >
              <Icon name="block" />
              {block.blocked ? t('artist.unblock') : t('artist.block')}
            </button>
          </>
        }
      />

      {(a.detailLevel === 'stub' || block.blocked) && (
        <div className="entity-banners">
          {a.detailLevel === 'stub' && (
            <p className="banner">
              <Icon name="info" size={20} />
              {t('artist.detail.stub')}
            </p>
          )}
          {block.blocked && (
            <p className="banner">
              <Icon name="block" size={20} />
              {t('artist.blocked')}
            </p>
          )}
        </div>
      )}

      <CollaborationsPanel artistId={id} />

      <ArtistRecommendations artistId={id} name={a.displayName} />

      {a.oftenPlayedWith.length > 0 && (
        <OftenPlayedWith entries={a.oftenPlayedWith} />
      )}

      {a.labels.length > 0 && <Labels labels={a.labels} />}

      {(a.aliases.length > 0 || a.links.length > 0 || a.sources.length > 0) && (
        <EntitySection id="artist-about" title={t('artist.about')}>
          <div className="entity-about">
            {a.aliases.length > 0 && <Aliases aliases={a.aliases} />}
            <Links artist={a} />
          </div>
        </EntitySection>
      )}
    </article>
  );
}
