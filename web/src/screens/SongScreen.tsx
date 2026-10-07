/** Song (S5): credits grouped by role, and the albums the song appears on. */
import {useParams} from 'react-router';

import type {Schemas} from '../api/client';
import {useRecording} from '../api/queries';
import {usePageTitle} from '../app/Shell';
import {ArtistRow} from '../components/ArtistRow';
import {hostOf} from '../components/evidence';
import {Icon} from '../components/Icon';
import {EmptyState, ErrorState, Spinner} from '../components/States';
import {useI18n} from '../i18n/i18n';
import type {MessageId} from '../i18n/messages';

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

function groupByRole(
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

export default function SongScreen() {
  const {t} = useI18n();
  const {id = ''} = useParams();
  const recording = useRecording(id);
  usePageTitle(recording.data?.displayName);

  if (recording.isPending) return <Spinner />;
  if (recording.isError)
    return (
      <ErrorState
        error={recording.error}
        onRetry={() => void recording.refetch()}
      />
    );
  const song = recording.data;
  const seconds = song.lengthMs ? Math.round(song.lengthMs / 1000) : null;

  return (
    <article className="stack" style={{gap: 'var(--space-6)'}}>
      <header className="stack" style={{gap: 'var(--space-1)'}}>
        <h1>
          <bdi>{song.displayName}</bdi>
        </h1>
        <p className="muted">
          {[
            song.firstReleaseDate?.slice(0, 4),
            seconds !== null
              ? t('song.length', {
                  minutes: Math.floor(seconds / 60),
                  seconds: String(seconds % 60).padStart(2, '0'),
                })
              : null,
          ]
            .filter(Boolean)
            .join(' · ')}
        </p>
      </header>

      <section className="section">
        <h2>{t('song.credits')}</h2>
        {song.credits.length === 0 ? (
          <EmptyState title={t('song.noCredits')} />
        ) : (
          groupByRole(song.credits).map(([role, credits]) => (
            <div key={role} className="stack" style={{gap: 'var(--space-1)'}}>
              <h3 className="muted" style={{font: 'var(--title-small)'}}>
                {t(
                  (ROLE_ORDER.includes(role)
                    ? `song.role.${role}`
                    : 'role.other') as MessageId,
                )}
              </h3>
              <ul className="list">
                {credits.map(credit => (
                  <ArtistRow
                    key={`${credit.artist.name}-${credit.roleDetail}`}
                    artist={credit.artist}
                    subtitle={[
                      credit.roleDetail,
                      credit.creditedAs !== credit.artist.displayName
                        ? credit.creditedAs
                        : '',
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

      {song.appearances.length > 0 && (
        <section className="section">
          <h2>{t('song.appearsOn')}</h2>
          <ul className="list">
            {song.appearances.map(appearance => (
              <li
                key={`${appearance.release}-${appearance.discNumber}-${appearance.position}`}
                className="list-row"
              >
                <span className="avatar" aria-hidden="true">
                  <Icon name="album" />
                </span>
                <span className="list-row__body">
                  <span className="list-row__title">
                    <bdi>{appearance.displayName}</bdi>
                  </span>
                  {appearance.year !== null && (
                    <span className="list-row__subtitle">
                      {appearance.year}
                    </span>
                  )}
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {song.sources.length > 0 && (
        <p className="muted" style={{font: 'var(--body-small)'}}>
          {song.sources.map(source => (
            <a
              key={source.url}
              href={source.url}
              target="_blank"
              rel="noopener noreferrer"
            >
              {t('connection.source', {host: hostOf(source.url)})}
            </a>
          ))}
        </p>
      )}
    </article>
  );
}
