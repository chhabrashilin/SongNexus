/**
 * Genre (v5): a hero whose art is a mosaic of the genre's most connected
 * artists, where it sits (parent genres, subgenres), then its artists: the
 * top ten as photo covers, the rest as ranked rows a page at a time.
 */
import {type CSSProperties} from 'react';
import {Link, useParams} from 'react-router';

import {idOf, type Schemas} from '../api/client';
import {useAmbient} from '../app/ambient';
import {usePageTitle} from '../app/Shell';
import {artistPath, imageOf} from '../components/ArtistRow';
import {Icon} from '../components/Icon';
import {Cover, CoverCard, Shelf} from '../components/Shelf';
import {useIntentPrefetch} from '../components/useIntentPrefetch';
import {
  EntityError,
  EntityHero,
  EntitySection,
  EntitySkeleton,
  ListenLink,
  Stats,
  useShowAll,
} from '../entity/Entity';
import {useGenre, useGenreArtists} from '../entity/queries';
import {useI18n} from '../i18n/i18n';

/** Artists shown as covers before the ranked rows begin. */
export const TOP = 10;

/** Splits a genre's artists into the covers shelf and the ranked rows after it. */
export function splitTop<T>(artists: T[], top = TOP): {top: T[]; rest: T[]} {
  return {top: artists.slice(0, top), rest: artists.slice(top)};
}

/** Four portraits of the genre's leading artists, photos first. */
function Mosaic({
  name,
  artists,
}: {
  name: string;
  artists: Schemas['GenreArtist'][];
}) {
  const withPhoto = artists.filter(a => imageOf(a.artist));
  const picks = [
    ...withPhoto,
    ...artists.filter(a => !imageOf(a.artist)),
  ].slice(0, 4);
  if (picks.length < 4) return <Cover name={name} eager />;
  return (
    <span className="genre-mosaic" aria-hidden="true">
      {picks.map(entry => (
        <Cover
          key={entry.artist.name}
          name={entry.artist.displayName}
          image={imageOf(entry.artist)}
          eager
        />
      ))}
    </span>
  );
}

function GenreChips({
  genres,
  label,
  limit,
}: {
  genres: Schemas['GenreRef'][];
  label: string;
  limit: number;
}) {
  const {formatNumber} = useI18n();
  const {visible, toggle} = useShowAll(genres, limit);
  return (
    <>
      <ul className="chips genre-chips" aria-label={label}>
        {visible.map(genre => (
          <li key={genre.name}>
            <Link className="chip" to={`/genre/${idOf(genre.name)}`}>
              <bdi>{genre.displayName}</bdi>
              <span className="genre-chips__count">
                {formatNumber(genre.artistCountWithSubgenres)}
              </span>
            </Link>
          </li>
        ))}
      </ul>
      {toggle}
    </>
  );
}

function RankRow({entry, rank}: {entry: Schemas['GenreArtist']; rank: number}) {
  const {t, formatNumber} = useI18n();
  const intent = useIntentPrefetch(idOf(entry.artist.name));
  return (
    <li style={{'--i': rank % 24} as CSSProperties}>
      <Link className="rank-row" to={artistPath(entry.artist)} {...intent}>
        <span className="rank-row__n">{formatNumber(rank)}</span>
        <Cover
          name={entry.artist.displayName}
          image={imageOf(entry.artist)}
          round
        />
        <span className="rank-row__text">
          <span className="rank-row__title">
            <bdi>{entry.artist.displayName}</bdi>
          </span>
          <span className="rank-row__sub">
            {t('genre.artist.sub', {
              count: entry.collaboratorCount,
              share: Math.round(entry.genreShare * 100),
            })}
          </span>
        </span>
      </Link>
    </li>
  );
}

export default function GenreScreen() {
  const {t, formatNumber} = useI18n();
  const {id = ''} = useParams();
  const genre = useGenre(id);
  const artists = useGenreArtists(id);
  usePageTitle(genre.data?.displayName);
  useAmbient(genre.data?.displayName ?? null);

  if (genre.isPending) return <EntitySkeleton kind="genre" body="covers" />;
  if (genre.isError)
    return (
      <EntityError
        kind="genre"
        error={genre.error}
        onRetry={() => void genre.refetch()}
      />
    );
  const g = genre.data;
  const all = artists.data?.pages.flatMap(page => page.artists) ?? [];
  const {top, rest} = splitTop(all);
  const leader = all[0];

  return (
    <article className="entity">
      <EntityHero
        kind="genre"
        name={g.displayName}
        art={<Mosaic name={g.displayName} artists={top} />}
        overline={t('genre.kind')}
        lead={
          g.memberCount > 0
            ? t('genre.lead', {count: g.memberCount})
            : t('genre.lead.empty')
        }
        meta={
          g.parents.length > 0 && (
            <div className="entity-hero__genres">
              <p className="entity-hero__note">{t('genre.partOf')}</p>
              <GenreChips
                genres={g.parents}
                label={t('genre.partOf')}
                limit={6}
              />
            </div>
          )
        }
        stats={
          <Stats
            label={t('genre.stat.label')}
            items={[
              {
                key: 'artists',
                value: formatNumber(g.memberCount),
                label: t('genre.stat.artists', {count: g.memberCount}),
              },
              {
                key: 'subgenres',
                value: g.children.length
                  ? formatNumber(g.children.length)
                  : null,
                label: t('genre.stat.subgenres', {count: g.children.length}),
              },
              {
                key: 'tagged',
                value: formatNumber(g.artistCountWithSubgenres),
                label: t('genre.stat.tagged', {
                  count: g.artistCountWithSubgenres,
                }),
              },
            ]}
          />
        }
        actions={
          <>
            {leader && (
              <Link
                className="btn btn--filled"
                to={`/explore/${idOf(leader.artist.name)}`}
              >
                <Icon name="explore" />
                {t('genre.exploreTop', {name: leader.artist.displayName})}
              </Link>
            )}
            <ListenLink query={g.displayName} />
          </>
        }
      />

      {g.children.length > 0 && (
        <EntitySection
          id="genre-children"
          title={t('genre.subgenres')}
          eyebrow={t('genre.subgenres.basis')}
        >
          <GenreChips
            genres={g.children}
            label={t('genre.subgenres')}
            limit={12}
          />
        </EntitySection>
      )}

      {artists.isPending ? (
        <section
          className="entity-section"
          aria-busy="true"
          aria-label={t('genre.top')}
        >
          <span className="skeleton entity-skeleton__line" data-w="l" />
          <div className="entity-covers" aria-hidden="true">
            {[0, 1, 2, 3, 4, 5].map(i => (
              <span key={i} className="stack">
                <span className="skeleton entity-skeleton__cover" />
                <span className="skeleton entity-skeleton__line" data-w="m" />
              </span>
            ))}
          </div>
        </section>
      ) : artists.isError ? (
        <EntitySection id="genre-artists" title={t('genre.top')}>
          <div className="entity-empty" role="alert">
            <Icon name="info" />
            <p>{t('state.error.body')}</p>
            <button
              type="button"
              className="btn btn--tonal btn--compact"
              onClick={() => void artists.refetch()}
            >
              {t('action.retry')}
            </button>
          </div>
        </EntitySection>
      ) : all.length === 0 ? (
        <EntitySection id="genre-artists" title={t('genre.top')}>
          <div className="entity-empty">
            <Icon name="people" />
            <p>{t('genre.noArtists')}</p>
          </div>
        </EntitySection>
      ) : (
        <>
          <Shelf eyebrow={t('genre.top.basis')} title={t('genre.top')}>
            {top.map((entry, index) => (
              <CoverCard
                key={entry.artist.name}
                to={artistPath(entry.artist)}
                title={entry.artist.displayName}
                subtitle={t('genre.collaborators', {
                  count: entry.collaboratorCount,
                })}
                image={imageOf(entry.artist)}
                badge={`#${index + 1}`}
                round
              />
            ))}
          </Shelf>
          {rest.length > 0 && (
            <EntitySection
              id="genre-artists"
              title={t('genre.all', {name: g.displayName})}
              eyebrow={t('genre.all.basis')}
            >
              <ol className="rank-grid stagger">
                {rest.map((entry, index) => (
                  <RankRow
                    key={entry.artist.name}
                    entry={entry}
                    rank={TOP + index + 1}
                  />
                ))}
              </ol>
              {artists.hasNextPage && (
                <button
                  type="button"
                  className="btn btn--tonal btn--compact entity-show-all"
                  disabled={artists.isFetchingNextPage}
                  onClick={() => void artists.fetchNextPage()}
                >
                  {artists.isFetchingNextPage
                    ? t('state.loading')
                    : t('genre.more', {
                        shown: formatNumber(all.length),
                        total: formatNumber(g.memberCount),
                      })}
                </button>
              )}
            </EntitySection>
          )}
        </>
      )}
    </article>
  );
}
