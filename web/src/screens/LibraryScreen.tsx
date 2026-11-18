/**
 * Library (S8, US-10, US-08): bring your music (connect a service or import a
 * file, read on this device), "Your Nexus" (what your artists say about your
 * taste), your listening as ranked rows and shelves, what friends sent, and
 * playlist maps. Files never leave the browser; matching sends artist names
 * only, and nothing from an import is stored unless you choose to save it.
 */
import {
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type DragEvent,
} from 'react';
import {Link} from 'react-router';

import {idOf, type ArtistSummary} from '../api/client';
import {useComputeTasteProfile, useTasteProfile} from '../api/personal';
import {
  useAnalyzePlaylist,
  useListening,
  useProfile,
  useUpdateProfile,
  type PlaylistAnalysis,
} from '../api/queries';
import {useInbox} from '../api/social';
import {ConnectedServices} from '../accounts/ConnectedServices';
import {useAmbient} from '../app/ambient';
import {useConfigFlags} from '../app/flags';
import {usePageTitle} from '../app/Shell';
import {useAuth} from '../auth/AuthProvider';
import {artistPath, imageOf} from '../components/ArtistRow';
import {Icon} from '../components/Icon';
import {Cover, CoverCard, Shelf} from '../components/Shelf';
import {useSnackbar} from '../components/Snackbar';
import {ErrorState} from '../components/States';
import {useI18n} from '../i18n/i18n';
import type {ArtistListening, Playlist} from '../importers/formats';
import type {FileOutcome} from '../importers/importFiles';
import {useImport} from '../importers/useImport';
import {PortraitChain} from '../social/Chain';
import {Block, Hero, PromiseLine} from '../social/Hero';
import {sharePath} from '../social/ShareSheet';
import {NexusSkeleton, YourNexus} from '../taste/YourNexus';

import {ago, shareTitle} from './FriendsScreen';

/** History imports match the most-listened artists only: the rest rarely matter and cost time. */
const MAX_HISTORY_ARTISTS = 500;
const ACCEPT = '.zip,.json,.jsonl,.csv,.tsv,.txt';
/** Ranked rows before "Show all". */
const TOP_ROWS = 10;

/** Matched artists' resource names, in the order they were found, without repeats. */
export function matchedNames(analysis: PlaylistAnalysis | undefined): string[] {
  const seen = new Set<string>();
  for (const row of analysis?.artists ?? [])
    if (row.status === 'MATCHED' && row.artist) seen.add(row.artist.name);
  return [...seen];
}

function RankRows({rows}: {rows: {artist: ArtistSummary; sub: string}[]}) {
  return (
    <ol className="rank-grid stagger">
      {rows.map((row, i) => (
        <li key={row.artist.name} style={{'--i': i} as CSSProperties}>
          <Link className="rank-row" to={artistPath(row.artist)}>
            <span className="rank-row__n">{i + 1}</span>
            <Cover
              name={row.artist.displayName}
              image={imageOf(row.artist)}
              round
            />
            <span className="rank-row__text">
              <span className="rank-row__title">
                <bdi>{row.artist.displayName}</bdi>
              </span>
              <span className="rank-row__sub">{row.sub}</span>
            </span>
          </Link>
        </li>
      ))}
    </ol>
  );
}

/** The hero's art: your most played artists as a fanned stack of records. */
function RecordStack({artists}: {artists: ArtistSummary[]}) {
  if (artists.length === 0)
    return (
      <div className="record-stack record-stack--empty">
        <span className="record-stack__disc" />
        <span className="record-stack__icon">
          <Icon name="library" size={40} />
        </span>
      </div>
    );
  return (
    <div className="record-stack">
      {artists.slice(0, 3).map((artist, i) => (
        <span key={artist.name} className="record-stack__item" data-i={i}>
          <Cover name={artist.displayName} image={imageOf(artist)} eager />
        </span>
      ))}
    </div>
  );
}

function FileDrop({
  inputId,
  onFiles,
}: {
  inputId: string;
  onFiles: (files: File[]) => void;
}) {
  const {t} = useI18n();
  const [dragging, setDragging] = useState(false);
  const onDrop = (event: DragEvent) => {
    event.preventDefault();
    setDragging(false);
    if (event.dataTransfer.files.length) onFiles([...event.dataTransfer.files]);
  };
  return (
    <div
      className="dropzone"
      data-dragging={dragging || undefined}
      onDragOver={event => {
        event.preventDefault();
        setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={onDrop}
    >
      <span className="dropzone__icon" aria-hidden="true">
        <Icon name="upload" size={28} />
      </span>
      <label htmlFor={inputId} className="btn btn--filled">
        <Icon name="library" />
        {t('library.choose')}
      </label>
      <span className="muted">{t('library.drop')}</span>
    </div>
  );
}

function Outcomes({outcomes}: {outcomes: FileOutcome[]}) {
  const {t} = useI18n();
  return (
    <section className="stack outcomes" aria-labelledby="files-title">
      <h3 id="files-title" className="outcomes__title">
        {t('library.files')}
      </h3>
      <ul className="outcomes__list">
        {outcomes.map(outcome => (
          <li key={outcome.file} className="outcome" data-ok={outcome.ok}>
            <Icon name={outcome.ok ? 'check' : 'info'} />
            <span className="outcome__body">
              <span className="outcome__file">
                <bdi>{outcome.file}</bdi>
              </span>
              <span className="outcome__detail">
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

/** "See the Nexus" for artists matched on this device (nothing is stored). */
function ComputedNexus({artists}: {artists: string[]}) {
  const {t} = useI18n();
  const compute = useComputeTasteProfile();
  if (artists.length === 0) return null;
  if (!compute.data && !compute.isPending && !compute.isError)
    return (
      <button
        type="button"
        className="btn btn--tonal nexus-cta"
        onClick={() => compute.mutate(artists)}
      >
        <Icon name="spark" />
        {t('taste.compute')}
      </button>
    );
  return (
    <section className="stack" aria-labelledby="computed-nexus">
      <h3 id="computed-nexus" className="outcomes__title">
        {t('taste.title')}
      </h3>
      {compute.isPending && <NexusSkeleton />}
      {compute.isError && (
        <ErrorState
          error={compute.error}
          onRetry={() => compute.mutate(artists)}
        />
      )}
      {compute.data && <YourNexus profile={compute.data} from="playlist" />}
    </section>
  );
}

function Cohesion({score}: {score: number | null}) {
  const {t} = useI18n();
  return (
    <div
      className="cohesion"
      style={{'--p': score ?? 0} as CSSProperties}
      data-none={score === null || undefined}
    >
      <span className="cohesion__ring" aria-hidden="true" />
      <p className="cohesion__text">
        {score === null
          ? t('analysis.cohesion.none')
          : t('analysis.cohesion', {percent: score})}
      </p>
    </div>
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
  const flags = useConfigFlags();
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
  const matched = matchedNames(result);
  const found = result?.artists.filter(a => a.status === 'MATCHED').length ?? 0;

  return (
    <section
      className="analysis"
      aria-labelledby="analysis-title"
      aria-live="polite"
    >
      <div className="block__header">
        <div className="shelf__titles">
          <p className="shelf__eyebrow">{t('analysis.eyebrow')}</p>
          <h2 id="analysis-title" className="block__title">
            <bdi>{t('analysis.title', {name: playlist.name})}</bdi>
          </h2>
        </div>
        <button
          type="button"
          className="icon-btn icon-btn--outlined"
          onClick={onClose}
        >
          <Icon name="close" label={t('action.close')} />
        </button>
      </div>
      {analyze.isPending && (
        <div className="analysis__skel" role="status">
          <span className="visually-hidden">{t('state.loading')}</span>
          <span className="skeleton analysis__skel-ring" />
          <span className="skeleton analysis__skel-rows" />
        </div>
      )}
      {analyze.isError && (
        <ErrorState
          error={analyze.error}
          onRetry={() => analyze.mutate(tracks)}
        />
      )}
      {result && (
        <>
          <div className="analysis__top">
            <Cohesion score={result.cohesion.score} />
            <div className="stack analysis__facts">
              <p className="analysis__found">
                {t('analysis.found', {
                  matched: found,
                  total: result.artists.length,
                })}
              </p>
              <p className="muted">{t('analysis.cohesion.help')}</p>
              <p className="muted">
                {t('analysis.links', {count: result.links.length})}
              </p>
            </div>
          </div>

          {result.artists.some(a => a.status === 'AMBIGUOUS') && (
            <div className="stack ambiguous">
              <h3 className="outcomes__title">{t('analysis.ambiguous')}</h3>
              {result.artists
                .filter(a => a.status === 'AMBIGUOUS')
                .map(row => (
                  <div key={row.query} className="stack ambiguous__row">
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
            <p className="quiet-note">
              <Icon name="info" />
              <span>
                {t('analysis.notFound', {
                  names: result.artists
                    .filter(a => a.status === 'NO_MATCH')
                    .slice(0, 12)
                    .map(a => a.query)
                    .join(', '),
                })}
              </span>
            </p>
          )}

          {result.thread.artists.length > 1 && (
            <div className="stack">
              <h3 className="outcomes__title">{t('analysis.thread')}</h3>
              <div className="chain-scroll">
                <PortraitChain
                  artists={result.thread.artists}
                  label={t('analysis.thread')}
                  ends={false}
                />
              </div>
              {result.thread.breaks > 0 && (
                <p className="muted">
                  {t('analysis.thread.breaks', {count: result.thread.breaks})}
                </p>
              )}
            </div>
          )}

          <div className="stack">
            <h3 className="outcomes__title">{t('analysis.connectors')}</h3>
            <p className="muted">{t('analysis.connectors.lead')}</p>
            {result.connectors.length === 0 ? (
              <p className="quiet-note">
                <Icon name="route" />
                <span>{t('analysis.connectors.none')}</span>
              </p>
            ) : (
              <RankRows
                rows={result.connectors.slice(0, 8).map(connector => ({
                  artist: connector.artist,
                  sub: t('analysis.connector.links', {
                    names: connector.linkedTo
                      .map(n => names.get(n) ?? '')
                      .filter(Boolean)
                      .join(', '),
                  }),
                }))}
              />
            )}
          </div>

          {flags.tasteProfile !== false && <ComputedNexus artists={matched} />}
        </>
      )}
    </section>
  );
}

function YourArtists({listening}: {listening: ArtistListening[]}) {
  const {t} = useI18n();
  const auth = useAuth();
  const flags = useConfigFlags();
  const snackbar = useSnackbar();
  const analyze = useAnalyzePlaylist();
  const profile = useProfile(auth.status === 'signedIn');
  const updateProfile = useUpdateProfile();
  const top = listening.slice(0, MAX_HISTORY_ARTISTS);
  const matched = (analyze.data?.artists ?? []).filter(
    a => a.status === 'MATCHED' && a.artist,
  );

  return (
    <Block
      id="your-artists-title"
      eyebrow={t('library.yourArtists.eyebrow')}
      title={t('library.yourArtists')}
    >
      <p className="muted">{t('library.yourArtists.lead')}</p>
      {!analyze.data && (
        <button
          type="button"
          className="btn btn--filled nexus-cta"
          disabled={analyze.isPending}
          onClick={() => analyze.mutate(top.map(a => [a.artist]))}
        >
          <Icon name="search" />
          {t('library.match')}
        </button>
      )}
      {analyze.isPending && (
        <div className="analysis__skel" role="status">
          <span className="visually-hidden">{t('state.loading')}</span>
          <span className="skeleton analysis__skel-rows" />
        </div>
      )}
      {analyze.isError && (
        <ErrorState
          error={analyze.error}
          onRetry={() => analyze.mutate(top.map(a => [a.artist]))}
        />
      )}
      {analyze.data && (
        <>
          <p className="analysis__found">
            {t('library.matchedOf', {
              matched: matched.length,
              total: top.length,
            })}
          </p>
          <RankRows
            rows={matched.slice(0, 20).map(row => ({
              artist: row.artist!,
              sub: t('library.yourArtists.matched'),
            }))}
          />
          {auth.status === 'signedIn' ? (
            <button
              type="button"
              className="btn btn--tonal nexus-cta"
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
              <Icon name="trophy" />
              {t('library.top5.suggest')}
            </button>
          ) : (
            <p className="muted">{t('library.top5.signIn')}</p>
          )}
          {flags.tasteProfile !== false && (
            <ComputedNexus artists={matchedNames(analyze.data)} />
          )}
        </>
      )}
    </Block>
  );
}

/** "Your Nexus" from linked accounts' listening (signed in). */
function NexusSection() {
  const {t} = useI18n();
  const auth = useAuth();
  const flags = useConfigFlags();
  const enabled = auth.status === 'signedIn' && flags.tasteProfile !== false;
  const profile = useTasteProfile(enabled);
  if (!enabled) return null;
  if (profile.isSuccess && profile.data.artistCount === 0) return null;
  return (
    <section
      id="your-nexus"
      className="block nexus-block"
      aria-labelledby="nexus-title"
    >
      <div className="block__header">
        <div className="shelf__titles">
          <p className="shelf__eyebrow">{t('taste.eyebrow')}</p>
          <h2 id="nexus-title" className="block__title">
            {t('taste.title')}
          </h2>
        </div>
      </div>
      <p className="muted nexus-block__lead">{t('taste.lead')}</p>
      {profile.isPending && <NexusSkeleton />}
      {profile.isError && (
        <ErrorState
          error={profile.error}
          onRetry={() => void profile.refetch()}
        />
      )}
      {profile.data && <YourNexus profile={profile.data} from="listening" />}
    </section>
  );
}

/** Artists from linked accounts (R2-6): synced on the server, aggregates only. */
function Listening({onConnect}: {onConnect: () => void}) {
  const {t} = useI18n();
  const listening = useListening(true, 50);
  const [all, setAll] = useState(false);
  const artists = listening.data?.artists ?? [];
  const rows = artists.slice(0, all ? 30 : TOP_ROWS);
  const rest = artists.slice(30);

  return (
    <Block
      id="listening-title"
      eyebrow={t('library.listening.eyebrow')}
      title={t('library.listening.title')}
    >
      {listening.isPending ? (
        <div className="rank-grid" role="status">
          <span className="visually-hidden">{t('state.loading')}</span>
          {Array.from({length: 6}, (_, i) => (
            <span key={i} className="skeleton rank-skel" aria-hidden="true" />
          ))}
        </div>
      ) : listening.isError ? (
        <ErrorState
          error={listening.error}
          onRetry={() => void listening.refetch()}
        />
      ) : artists.length === 0 ? (
        <div className="empty-card">
          <Icon name="sync" size={32} />
          <p className="empty-card__title">
            {t('library.listening.emptyTitle')}
          </p>
          <p className="muted">{t('library.listening.empty')}</p>
          <button type="button" className="btn btn--tonal" onClick={onConnect}>
            {t('library.listening.connect')}
          </button>
        </div>
      ) : (
        <>
          <RankRows
            rows={rows.map(row => ({
              artist: row.artist,
              sub: t('library.listening.plays', {count: row.plays}),
            }))}
          />
          {artists.length > TOP_ROWS && (
            <button
              type="button"
              className="btn btn--outlined block__more"
              aria-expanded={all}
              onClick={() => setAll(value => !value)}
            >
              {all
                ? t('library.listening.fewer')
                : t('library.listening.all', {
                    count: Math.min(30, artists.length),
                  })}
            </button>
          )}
          {rest.length > 0 && (
            <Shelf
              eyebrow={t('library.listening.deeper.eyebrow')}
              title={t('library.listening.deeper')}
            >
              {rest.map(row => (
                <CoverCard
                  key={row.artist.name}
                  to={artistPath(row.artist)}
                  title={row.artist.displayName}
                  subtitle={t('library.listening.plays', {count: row.plays})}
                  image={imageOf(row.artist)}
                  round
                />
              ))}
            </Shelf>
          )}
        </>
      )}
    </Block>
  );
}

/** R2-7: what friends recommended, as a shelf; opens the Friends inbox for the rest. */
function FromFriends() {
  const {t} = useI18n();
  const auth = useAuth();
  const flags = useConfigFlags();
  const inbox = useInbox(auth.status === 'signedIn' && flags.friends !== false);
  const shares = (inbox.data?.shares ?? []).filter(s =>
    s.subjects.every(x => x.available),
  );
  if (shares.length === 0) return null;
  return (
    <Shelf
      eyebrow={t('library.friends.eyebrow')}
      title={t('library.friends.title')}
      action={
        <Link className="btn btn--outlined btn--compact" to="/friends">
          {t('action.showMore')}
        </Link>
      }
    >
      {shares.slice(0, 20).map(share => (
        <CoverCard
          key={share.name}
          to={sharePath(
            share.kind,
            share.subjects.map(s => s.name),
          )}
          title={shareTitle(t, share)}
          subtitle={t('friends.share.from', {
            name: share.sender.displayName,
            when: ago(t, share.createTime),
          })}
          round={share.kind === 'ARTIST'}
        />
      ))}
    </Shelf>
  );
}

export default function LibraryScreen() {
  const {t} = useI18n();
  const auth = useAuth();
  const inputId = useId();
  const services = useRef<HTMLDivElement>(null);
  const importer = useRef<HTMLLIElement>(null);
  const {state, start, cancel} = useImport();
  const [selected, setSelected] = useState<Playlist | null>(null);
  const signedIn = auth.status === 'signedIn';
  const listening = useListening(signedIn, 50);
  const top = (listening.data?.artists ?? []).map(row => row.artist);
  usePageTitle(t('library.title'));
  useAmbient(top[0]?.displayName ?? null);

  const outcomes = state.status === 'done' ? state.outcomes : [];
  const playlists = outcomes.flatMap(o =>
    o.ok && o.parsed.kind === 'playlists' ? o.parsed.playlists : [],
  );
  const history = useMemo(() => {
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

  function toServices() {
    if (!signedIn) {
      void auth.signIn();
      return;
    }
    services.current?.scrollIntoView({behavior: 'smooth', block: 'start'});
  }

  function onFiles(files: File[]) {
    setSelected(null);
    start(files);
    importer.current?.scrollIntoView({behavior: 'smooth', block: 'start'});
  }

  return (
    <div className="library">
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
      <Hero
        overline={t('nav.library')}
        icon="library"
        title={t('library.title')}
        hue={top[0]?.displayName ?? 'Library'}
        body={<p>{t('library.lead')}</p>}
        actions={
          <>
            <button
              type="button"
              className="btn btn--filled"
              onClick={toServices}
              disabled={auth.status === 'signingIn'}
            >
              <Icon name="sync" />
              {t('library.hero.connect')}
            </button>
            <label htmlFor={inputId} className="btn btn--tonal">
              <Icon name="upload" />
              {t('library.hero.import')}
            </label>
          </>
        }
        footnote={<PromiseLine>{t('library.promise')}</PromiseLine>}
        art={<RecordStack artists={top} />}
      />

      <NexusSection />

      {signedIn && <Listening onConnect={toServices} />}

      <FromFriends />

      <Block
        id="bring-title"
        eyebrow={t('library.bring.eyebrow')}
        title={t('library.bring.title')}
      >
        <ol className="bring">
          <li className="bring__step">
            <span className="bring__n" aria-hidden="true">
              1
            </span>
            <h3 className="bring__title">{t('library.bring.connect')}</h3>
            <p className="muted">{t('library.bring.connect.body')}</p>
            <button
              type="button"
              className="btn btn--tonal"
              onClick={toServices}
              disabled={auth.status === 'signingIn'}
            >
              <Icon name={signedIn ? 'sync' : 'person'} />
              {signedIn
                ? t('library.bring.connect.action')
                : t('library.bring.connect.signIn')}
            </button>
          </li>
          <li className="bring__step bring__step--import" ref={importer}>
            <span className="bring__n" aria-hidden="true">
              2
            </span>
            <h3 className="bring__title">{t('library.privacy.title')}</h3>
            <p className="muted">{t('library.privacy.body')}</p>
            {state.status === 'running' ? (
              <div className="import-progress" role="status">
                <progress
                  max={state.progress.total}
                  value={state.progress.done}
                />
                <span>
                  {t('library.readProgress', {
                    done: state.progress.done,
                    total: state.progress.total,
                  })}
                  {state.progress.current &&
                    ` · ${t('library.reading', {current: state.progress.current})}`}
                </span>
                <button
                  type="button"
                  className="btn btn--text"
                  onClick={cancel}
                >
                  {t('library.cancel')}
                </button>
              </div>
            ) : (
              <FileDrop inputId={inputId} onFiles={onFiles} />
            )}
            <details className="more">
              <summary>{t('library.howTo')}</summary>
              <ul className="more__body howto">
                <li>{t('library.howTo.spotify')}</li>
                <li>{t('library.howTo.youtube')}</li>
                <li>{t('library.howTo.listenbrainz')}</li>
                <li>{t('library.howTo.csv')}</li>
              </ul>
            </details>
          </li>
        </ol>
        {state.status === 'failed' && (
          <p className="banner banner--error" role="alert">
            <Icon name="info" />
            <span>{t('library.failed')}</span>
          </p>
        )}
        {outcomes.length > 0 && <Outcomes outcomes={outcomes} />}
        {playlists.length > 0 && (
          <section className="stack" aria-labelledby="playlists-title">
            <h3 id="playlists-title" className="outcomes__title">
              {t('library.playlists')}
            </h3>
            <ul className="playlist-cards">
              {playlists.map((playlist, i) => (
                <li
                  key={`${playlist.name}-${i}`}
                  className="playlist-card"
                  data-selected={selected === playlist || undefined}
                >
                  <Cover name={playlist.name} icon="note" />
                  <span className="playlist-card__text">
                    <span className="playlist-card__name">
                      <bdi>{playlist.name}</bdi>
                    </span>
                    <span className="playlist-card__sub">
                      {t('library.playlist.tracks', {
                        count: playlist.tracks.length,
                      })}
                    </span>
                  </span>
                  <button
                    type="button"
                    className="btn btn--tonal btn--compact"
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
      </Block>

      {selected && (
        <AnalysisView
          key={selected.name}
          playlist={selected}
          onClose={() => setSelected(null)}
        />
      )}

      {history.length > 0 && <YourArtists listening={history} />}

      {signedIn && (
        <div ref={services} className="library__services">
          <ConnectedServices />
        </div>
      )}
    </div>
  );
}
