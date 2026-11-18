/**
 * Song (S5, v5): a hero with generated cover art (we hold no album-art
 * rights), who made it, "Listen on YouTube Music"; then its sound, the
 * performers as covers, every other credit grouped by role, and the releases
 * it appears on.
 */
import {Fragment, type CSSProperties} from 'react';
import {Link, useParams} from 'react-router';

import type {Schemas} from '../api/client';
import {useRecording} from '../api/queries';
import {useAmbient} from '../app/ambient';
import {usePageTitle} from '../app/Shell';
import {ArtistRow, artistPath, imageOf} from '../components/ArtistRow';
import {hostOf} from '../components/evidence';
import {Icon} from '../components/Icon';
import {Cover, CoverCard} from '../components/Shelf';
import {
  EntityError,
  EntityHero,
  EntitySection,
  EntitySkeleton,
  ListenLink,
  Stats,
  useShowAll,
} from '../entity/Entity';
import {duration, yearOf} from '../entity/facts';
import {useI18n} from '../i18n/i18n';
import type {MessageId} from '../i18n/messages';
import {ShareButton} from '../social/ShareSheet';
import {SoundProfile} from '../songs/Descriptors';

const ROLE_ORDER = [
  'primary',
  'featured',
  'producer',
  'vocal',
  'instrument',
  'performer',
  'programming',
  'arranger',
  'conductor',
  'remixer',
  'sampled',
  'engineer',
];

/** Roles shown as covers at the top: the people the song is "by". */
const PERFORMING = new Set(['primary', 'featured']);

export function groupByRole(
  credits: Schemas['Credit'][],
): [string, Schemas['Credit'][]][] {
  const groups = new Map<string, Schemas['Credit'][]>();
  for (const credit of credits) {
    groups.set(credit.role, [...(groups.get(credit.role) ?? []), credit]);
  }
  return [...groups.entries()].sort(
    ([x], [y]) =>
      (ROLE_ORDER.indexOf(x) + 1 || 99) - (ROLE_ORDER.indexOf(y) + 1 || 99),
  );
}

/** One entry per artist (a producer credited twice is one person). */
export function uniqueArtists(credits: Schemas['Credit'][]): number {
  return new Set(credits.map(c => c.artist.name)).size;
}

function roleName(role: string): MessageId {
  return (
    ROLE_ORDER.includes(role) ? `song.role.${role}` : 'role.other'
  ) as MessageId;
}

function creditSubtitle(credit: Schemas['Credit']): string {
  return [
    credit.roleDetail,
    credit.creditedAs && credit.creditedAs !== credit.artist.displayName
      ? credit.creditedAs
      : '',
  ]
    .filter(Boolean)
    .join(' · ');
}

/** Linked names: "Kendrick Lamar, SZA". */
function Names({credits}: {credits: Schemas['Credit'][]}) {
  const seen = new Set<string>();
  const unique = credits.filter(c =>
    seen.has(c.artist.name) ? false : (seen.add(c.artist.name), true),
  );
  return (
    <>
      {unique.map((credit, index) => (
        <Fragment key={credit.artist.name}>
          {index > 0 && ', '}
          <Link to={artistPath(credit.artist)}>
            <bdi>{credit.artist.displayName}</bdi>
          </Link>
        </Fragment>
      ))}
    </>
  );
}

function RoleGroup({
  role,
  credits,
}: {
  role: string;
  credits: Schemas['Credit'][];
}) {
  const {t, formatNumber} = useI18n();
  const {visible, toggle} = useShowAll(credits, 8);
  return (
    <div className="entity-role">
      <h3 className="entity-role__title">
        {t(roleName(role))}
        <span className="badge">{formatNumber(credits.length)}</span>
      </h3>
      <ul className="list">
        {visible.map((credit, index) => (
          <ArtistRow
            key={`${credit.artist.name}-${credit.roleDetail}-${index}`}
            artist={credit.artist}
            subtitle={creditSubtitle(credit) || credit.artist.disambiguation}
          />
        ))}
      </ul>
      {toggle}
    </div>
  );
}

function Appearances({items}: {items: Schemas['Appearance'][]}) {
  const {t} = useI18n();
  const {visible, toggle} = useShowAll(items, 8);
  return (
    <EntitySection id="song-appears" title={t('song.appearsOn')}>
      <ul className="entity-cards stagger">
        {visible.map((appearance, index) => (
          <li
            key={`${appearance.release}-${appearance.discNumber}-${appearance.position}`}
            style={{'--i': index} as CSSProperties}
          >
            <div className="entity-card" data-static>
              <Cover name={appearance.displayName} />
              <span className="entity-card__text">
                <span className="entity-card__title">
                  <bdi>{appearance.displayName}</bdi>
                </span>
                <span className="entity-card__sub">
                  {[
                    appearance.year,
                    t('song.track', {number: appearance.position}),
                  ]
                    .filter(Boolean)
                    .join(' · ')}
                </span>
              </span>
            </div>
          </li>
        ))}
      </ul>
      {toggle}
    </EntitySection>
  );
}

export default function SongScreen() {
  const {t, formatNumber} = useI18n();
  const {id = ''} = useParams();
  const recording = useRecording(id);
  usePageTitle(recording.data?.displayName);
  useAmbient(recording.data?.displayName ?? null);

  if (recording.isPending) return <EntitySkeleton kind="song" />;
  if (recording.isError)
    return (
      <EntityError
        kind="song"
        error={recording.error}
        onRetry={() => void recording.refetch()}
      />
    );
  const song = recording.data;
  const length = duration(song.lengthMs);
  const year = yearOf(song.firstReleaseDate);
  const groups = groupByRole(song.credits);
  const primary = song.credits.filter(c => c.role === 'primary');
  const featured = song.credits.filter(c => c.role === 'featured');
  const performers = song.credits.filter(c => PERFORMING.has(c.role));
  const others = groups.filter(([role]) => !PERFORMING.has(role));
  const listenQuery = [song.displayName, primary[0]?.artist.displayName]
    .filter(Boolean)
    .join(' ');
  const firstRelease = song.appearances[0];

  return (
    <article className="entity">
      <EntityHero
        kind="song"
        name={song.displayName}
        overline={[t('search.type.RECORDING'), year]
          .filter(Boolean)
          .join(' · ')}
        lead={
          primary.length > 0 || featured.length > 0 ? (
            <span className="entity-hero__by">
              {primary.length > 0 && <Names credits={primary} />}
              {featured.length > 0 && (
                <>
                  {primary.length > 0 && ' '}
                  <span className="muted">{t('song.featuring')}</span>{' '}
                  <Names credits={featured} />
                </>
              )}
            </span>
          ) : null
        }
        meta={
          (length || firstRelease) && (
            <p className="entity-hero__note">
              {[
                length ? t('song.length', length) : null,
                firstRelease
                  ? t('song.fromRelease', {release: firstRelease.displayName})
                  : null,
              ]
                .filter(Boolean)
                .join(' · ')}
            </p>
          )
        }
        stats={
          <Stats
            label={t('song.stat.label')}
            items={[
              {
                key: 'people',
                value: song.credits.length
                  ? formatNumber(uniqueArtists(song.credits))
                  : null,
                label: t('song.stat.people', {
                  count: uniqueArtists(song.credits),
                }),
              },
              {
                key: 'roles',
                value: groups.length ? formatNumber(groups.length) : null,
                label: t('song.stat.roles', {count: groups.length}),
              },
              {
                key: 'releases',
                value: song.appearances.length
                  ? formatNumber(song.appearances.length)
                  : null,
                label: t('song.stat.releases', {
                  count: song.appearances.length,
                }),
              },
            ]}
          />
        }
        actions={
          <>
            <ListenLink query={listenQuery} primary />
            <Link className="btn btn--tonal" to={`/compare/songs?a=${id}`}>
              <Icon name="compare" />
              {t('song.compare')}
            </Link>
            <ShareButton
              kind="RECORDING"
              subjects={[song.name]}
              title={song.displayName}
            />
          </>
        }
      />

      <EntitySection
        id="song-sound"
        title={t('song.sound')}
        eyebrow={t('song.sound.lead')}
      >
        {song.descriptors ? (
          <SoundProfile descriptors={song.descriptors} />
        ) : (
          <div className="entity-empty">
            <Icon name="note" />
            <p>{t('song.sound.none')}</p>
          </div>
        )}
      </EntitySection>

      {performers.length > 0 && (
        <EntitySection id="song-artists" title={t('song.artists')}>
          <ul className="entity-covers stagger">
            {performers.map(credit => (
              <CoverCard
                key={`${credit.artist.name}-${credit.role}`}
                to={artistPath(credit.artist)}
                title={credit.artist.displayName}
                subtitle={t(roleName(credit.role))}
                image={imageOf(credit.artist)}
                round
              />
            ))}
          </ul>
        </EntitySection>
      )}

      <EntitySection id="song-credits" title={t('song.credits')}>
        {song.credits.length === 0 ? (
          <div className="entity-empty">
            <Icon name="people" />
            <p>{t('song.noCredits')}</p>
          </div>
        ) : others.length === 0 ? (
          <p className="muted">{t('song.onlyPerformers')}</p>
        ) : (
          <div className="entity-roles">
            {others.map(([role, credits]) => (
              <RoleGroup key={role} role={role} credits={credits} />
            ))}
          </div>
        )}
      </EntitySection>

      {song.appearances.length > 0 && <Appearances items={song.appearances} />}

      {song.sources.length > 0 && (
        <p className="entity-sources">
          {song.sources.map(source => (
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
