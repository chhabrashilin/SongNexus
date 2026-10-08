/**
 * Library (S8, US-10, US-08): import listening data on the device, map a
 * playlist, and see "Your artists". Files never leave the browser; analysis
 * sends artist names only.
 */
import {useEffect, useId, useMemo, useState, type DragEvent} from 'react';
import {Link} from 'react-router';

import {idOf, type ArtistSummary} from '../api/client';
import {
  useAnalyzePlaylist,
  useProfile,
  useUpdateProfile,
  type PlaylistAnalysis,
} from '../api/queries';
import {usePageTitle} from '../app/Shell';
import {useAuth} from '../auth/AuthProvider';
import {ArtistRow, artistPath} from '../components/ArtistRow';
import {Icon} from '../components/Icon';
import {useSnackbar} from '../components/Snackbar';
import {ErrorState, SkeletonRows} from '../components/States';
import {useI18n} from '../i18n/i18n';
import type {ArtistListening, Playlist} from '../importers/formats';
import type {FileOutcome} from '../importers/importFiles';
import {useImport} from '../importers/useImport';

/** History imports match the most-listened artists only: the rest rarely matter and cost time. */
const MAX_HISTORY_ARTISTS = 500;
const ACCEPT = '.zip,.json,.jsonl,.csv,.tsv,.txt';

function PrivacyCard() {
  const {t} = useI18n();
  return (
    <section className="card stack" style={{gap: 'var(--space-2)'}}>
      <h2>{t('library.privacy.title')}</h2>
      <p className="muted">{t('library.privacy.body')}</p>
      <details>
        <summary
          style={{
            cursor: 'pointer',
            minBlockSize: 'var(--touch-target)',
            display: 'flex',
            alignItems: 'center',
          }}
        >
          {t('library.howTo')}
        </summary>
        <ul>
          <li>{t('library.howTo.spotify')}</li>
          <li>{t('library.howTo.youtube')}</li>
          <li>{t('library.howTo.listenbrainz')}</li>
          <li>{t('library.howTo.csv')}</li>
        </ul>
      </details>
    </section>
  );
}

function FilePicker({onFiles}: {onFiles: (files: File[]) => void}) {
  const {t} = useI18n();
  const inputId = useId();
  const [dragging, setDragging] = useState(false);
  const onDrop = (event: DragEvent) => {
    event.preventDefault();
    setDragging(false);
    if (event.dataTransfer.files.length) onFiles([...event.dataTransfer.files]);
  };
  return (
    <div
      className="card card--outlined stack"
      style={{
        alignItems: 'center',
        borderStyle: 'dashed',
        background: dragging ? 'var(--md-secondary-container)' : undefined,
      }}
      onDragOver={event => {
        event.preventDefault();
        setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={onDrop}
    >
      <label htmlFor={inputId} className="btn btn--filled">
        <Icon name="library" />
        {t('library.choose')}
      </label>
      <input
        id={inputId}
        type="file"
        multiple
        accept={ACCEPT}
        className="visually-hidden"
        onChange={event => {
          if (event.target.files?.length) onFiles([...event.target.files]);
          event.target.value = '';
        }}
      />
      <span className="muted">{t('library.drop')}</span>
    </div>
  );
}

function Outcomes({outcomes}: {outcomes: FileOutcome[]}) {
  const {t} = useI18n();
  return (
    <section className="section">
      <h2>{t('library.files')}</h2>
      <ul className="list">
        {outcomes.map(outcome => (
          <li key={outcome.file} className="list-row">
            <Icon name={outcome.ok ? 'check' : 'close'} />
            <span className="list-row__body">
              <span className="list-row__title">{outcome.file}</span>
              <span className="list-row__subtitle">
                {!outcome.ok
                  ? t(`library.reject.${outcome.reason}`)
                  : outcome.parsed.kind === 'playlists'
                    ? t('library.file.playlists', {
                        count: outcome.parsed.playlists.length,
                      })
                    : t('library.file.artists', {
                        count: outcome.parsed.artists.length,
                      })}
              </span>
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function AnalysisView({
  playlist,
  onClose,
}: {
  playlist: Playlist;
  onClose: () => void;
}) {
  const {t} = useI18n();
  const analyze = useAnalyzePlaylist();
  // A user's pick for an ambiguous name: name -> "artists/{id}".
  const [choices, setChoices] = useState<Record<string, string>>({});
  const tracks = useMemo(
    () =>
      playlist.tracks.map(track =>
        track.artists.map(artist => choices[artist] ?? artist),
      ),
    [playlist, choices],
  );
  const {mutate} = analyze;
  // Re-analyze whenever the user resolves an ambiguous name.
  useEffect(() => mutate(tracks), [mutate, tracks]);
  const result: PlaylistAnalysis | undefined = analyze.data;
  const names = useMemo(() => {
    const map = new Map<string, string>();
    for (const row of result?.artists ?? [])
      if (row.artist) map.set(row.artist.name, row.artist.displayName);
    return map;
  }, [result]);

  return (
    <section className="card stack" aria-live="polite">
      <div className="section__header">
        <h2>{t('analysis.title', {name: playlist.name})}</h2>
        <button type="button" className="icon-btn" onClick={onClose}>
          <Icon name="close" label={t('action.close')} />
        </button>
      </div>
      {analyze.isPending && <SkeletonRows count={4} />}
      {analyze.isError && (
        <ErrorState
          error={analyze.error}
          onRetry={() => analyze.mutate(tracks)}
        />
      )}
      {result && (
        <>
          <p
            style={{font: 'var(--headline-small)'}}
            title={t('analysis.cohesion.help')}
          >
            {result.cohesion.score === null
              ? t('analysis.cohesion.none')
              : t('analysis.cohesion', {percent: result.cohesion.score})}
          </p>
          <p className="muted">{t('analysis.cohesion.help')}</p>
          <p>
            {t('analysis.found', {
              matched: result.artists.filter(a => a.status === 'MATCHED')
                .length,
              total: result.artists.length,
            })}
          </p>

          {result.artists.some(a => a.status === 'AMBIGUOUS') && (
            <div className="stack" style={{gap: 'var(--space-2)'}}>
              <h3>{t('analysis.ambiguous')}</h3>
              {result.artists
                .filter(a => a.status === 'AMBIGUOUS')
                .map(row => (
                  <div
                    key={row.query}
                    className="stack"
                    style={{gap: 'var(--space-1)'}}
                  >
                    <strong>
                      <bdi>{row.query}</bdi>
                    </strong>
                    <div className="chips">
                      {row.candidates.map(candidate => (
                        <button
                          key={candidate.name}
                          type="button"
                          className="chip"
                          onClick={() =>
                            setChoices(previous => ({
                              ...previous,
                              [row.query]: candidate.name,
                            }))
                          }
                        >
                          {t('analysis.ambiguous.pick', {
                            name: [
                              candidate.displayName,
                              candidate.disambiguation,
                            ]
                              .filter(Boolean)
                              .join(' · '),
                          })}
                        </button>
                      ))}
                    </div>
                  </div>
                ))}
            </div>
          )}

          {result.artists.some(a => a.status === 'NO_MATCH') && (
            <p className="muted">
              {t('analysis.notFound', {
                names: result.artists
                  .filter(a => a.status === 'NO_MATCH')
                  .slice(0, 12)
                  .map(a => a.query)
                  .join(', '),
              })}
            </p>
          )}

          <h3>{t('analysis.connectors')}</h3>
          <p className="muted">{t('analysis.connectors.lead')}</p>
          {result.connectors.length === 0 ? (
            <p className="muted">{t('analysis.connectors.none')}</p>
          ) : (
            <ul className="list">
              {result.connectors.map(connector => (
                <ArtistRow
                  key={connector.artist.name}
                  artist={connector.artist}
                  subtitle={t('analysis.connector.links', {
                    names: connector.linkedTo
                      .map(n => names.get(n) ?? '')
                      .filter(Boolean)
                      .join(', '),
                  })}
                />
              ))}
            </ul>
          )}

          <h3>{t('analysis.thread')}</h3>
          <p>
            {result.thread.artists.map((artist: ArtistSummary, i) => (
              <span key={`${artist.name}-${i}`}>
                {i > 0 && ' → '}
                <Link to={artistPath(artist)}>
                  <bdi>{artist.displayName}</bdi>
                </Link>
              </span>
            ))}
          </p>
          {result.thread.breaks > 0 && (
            <p className="muted">
              {t('analysis.thread.breaks', {count: result.thread.breaks})}
            </p>
          )}
          <p className="muted">
            {t('analysis.links', {count: result.links.length})}
          </p>
        </>
      )}
    </section>
  );
}

function YourArtists({listening}: {listening: ArtistListening[]}) {
  const {t} = useI18n();
  const auth = useAuth();
  const snackbar = useSnackbar();
  const analyze = useAnalyzePlaylist();
  const profile = useProfile(auth.status === 'signedIn');
  const updateProfile = useUpdateProfile();
  const top = listening.slice(0, MAX_HISTORY_ARTISTS);
  const matched = (analyze.data?.artists ?? []).filter(
    a => a.status === 'MATCHED' && a.artist,
  );

  return (
    <section className="section">
      <h2>{t('library.yourArtists')}</h2>
      <p className="muted">{t('library.yourArtists.lead')}</p>
      {!analyze.data && (
        <button
          type="button"
          className="btn btn--tonal"
          disabled={analyze.isPending}
          onClick={() => analyze.mutate(top.map(a => [a.artist]))}
        >
          {t('library.match')}
        </button>
      )}
      {analyze.isPending && <SkeletonRows count={5} />}
      {analyze.isError && (
        <ErrorState
          error={analyze.error}
          onRetry={() => analyze.mutate(top.map(a => [a.artist]))}
        />
      )}
      {analyze.data && (
        <>
          <p className="muted">
            {t('library.matchedOf', {
              matched: matched.length,
              total: top.length,
            })}
          </p>
          <ol className="list">
            {matched.slice(0, 20).map(row => (
              <ArtistRow key={row.artist!.name} artist={row.artist!} />
            ))}
          </ol>
          {auth.status === 'signedIn' ? (
            <button
              type="button"
              className="btn btn--filled"
              disabled={
                matched.length === 0 || !profile.data || updateProfile.isPending
              }
              onClick={() =>
                updateProfile.mutate(
                  {
                    topArtists: matched
                      .slice(0, 5)
                      .map(r => `artists/${idOf(r.artist!.name)}`),
                    etag: profile.data!.etag,
                  },
                  {onSuccess: () => snackbar(t('library.top5.saved'))},
                )
              }
            >
              {t('library.top5.suggest')}
            </button>
          ) : (
            <p className="muted">{t('library.top5.signIn')}</p>
          )}
        </>
      )}
    </section>
  );
}

export default function LibraryScreen() {
  const {t} = useI18n();
  const {state, start, cancel} = useImport();
  const [selected, setSelected] = useState<Playlist | null>(null);
  usePageTitle(t('library.title'));

  const outcomes = state.status === 'done' ? state.outcomes : [];
  const playlists = outcomes.flatMap(o =>
    o.ok && o.parsed.kind === 'playlists' ? o.parsed.playlists : [],
  );
  const listening = useMemo(() => {
    const merged = new Map<string, ArtistListening>();
    for (const o of outcomes) {
      if (!o.ok || o.parsed.kind !== 'listening') continue;
      for (const a of o.parsed.artists) {
        const entry = merged.get(a.artist) ?? {
          artist: a.artist,
          plays: 0,
          msPlayed: 0,
        };
        entry.plays += a.plays;
        entry.msPlayed += a.msPlayed;
        merged.set(a.artist, entry);
      }
    }
    return [...merged.values()].sort(
      (a, b) => b.msPlayed - a.msPlayed || b.plays - a.plays,
    );
  }, [outcomes]);

  return (
    <div className="stack" style={{gap: 'var(--space-5)'}}>
      <header className="stack" style={{gap: 'var(--space-2)'}}>
        <h1>{t('library.title')}</h1>
        <p className="muted">{t('library.lead')}</p>
      </header>
      <PrivacyCard />

      {state.status === 'running' ? (
        <div className="card stack" role="status">
          <progress
            max={state.progress.total}
            value={state.progress.done}
            style={{inlineSize: '100%'}}
          />
          <span>
            {t('library.readProgress', {
              done: state.progress.done,
              total: state.progress.total,
            })}
            {state.progress.current &&
              ` · ${t('library.reading', {current: state.progress.current})}`}
          </span>
          <button type="button" className="btn btn--text" onClick={cancel}>
            {t('library.cancel')}
          </button>
        </div>
      ) : (
        <FilePicker
          onFiles={files => {
            setSelected(null);
            start(files);
          }}
        />
      )}
      {state.status === 'failed' && (
        <p className="banner banner--error">{t('library.failed')}</p>
      )}
      {outcomes.length > 0 && <Outcomes outcomes={outcomes} />}

      {selected && (
        <AnalysisView
          key={selected.name}
          playlist={selected}
          onClose={() => setSelected(null)}
        />
      )}

      {playlists.length > 0 && (
        <section className="section">
          <h2>{t('library.playlists')}</h2>
          <ul className="list">
            {playlists.map((playlist, i) => (
              <li
                key={`${playlist.name}-${i}`}
                className="row"
                style={{flexWrap: 'nowrap'}}
              >
                <span className="list-row" style={{flex: 1, minInlineSize: 0}}>
                  <span className="list-row__body">
                    <span className="list-row__title">
                      <bdi>{playlist.name}</bdi>
                    </span>
                    <span className="list-row__subtitle">
                      {t('library.playlist.tracks', {
                        count: playlist.tracks.length,
                      })}
                    </span>
                  </span>
                </span>
                <button
                  type="button"
                  className="btn btn--tonal"
                  disabled={playlist.tracks.length === 0}
                  onClick={() => setSelected(playlist)}
                >
                  {t('library.analyze')}
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}

      {listening.length > 0 && <YourArtists listening={listening} />}
    </div>
  );
}
