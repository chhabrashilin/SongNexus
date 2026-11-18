/**
 * Find a path (S2, US-03): pick two artists and see the chain of real credits
 * between them as a journey of portraits, each step opening to its credits and
 * their sources, then the same path as a mixtape: one real song per step.
 *
 * All state lives in the URL, so a shared link shows the same path to anyone
 * (AC-3.4).
 */
import {useEffect, useMemo, useState, type CSSProperties} from 'react';
import {Link, useSearchParams} from 'react-router';

import {idOf, type ArtistSummary} from '../api/client';
import {
  useArtist,
  usePath,
  type ConnectionCategory,
  type PathMode,
} from '../api/queries';
import {useAmbient} from '../app/ambient';
import {useGenreSelection} from '../app/genreSelection';
import {usePageTitle} from '../app/Shell';
import {useStarterArtists} from '../app/starters';
import {imageOf} from '../components/ArtistRow';
import {useListFormat} from '../components/AskAnswer';
import {EvidenceList} from '../components/ConnectionSheet';
import {
  CATEGORIES,
  CATEGORY_ENCODING,
  DEFAULT_CATEGORIES,
} from '../components/encoding';
import {CategoryChips, GenreFilter, Swatch} from '../components/Filters';
import {Icon} from '../components/Icon';
import {useSnackbar} from '../components/Snackbar';
import {ErrorState} from '../components/States';
import {
  mixtapeOf,
  mixtapeText,
  songPath,
  stepCategory,
  surprisePair,
  trackQuery,
  tracksOf,
  yearSpan,
  type PathStep,
  type PathTrack,
} from '../connect/mixtape';
import {
  ArtistSlot,
  ListenLink,
  Moment,
  Portrait,
  PortraitChain,
  SongCover,
  ToolHero,
} from '../connect/parts';
import {useI18n} from '../i18n/i18n';
import {ShareButton} from '../social/ShareSheet';

const STEP_MS = 420;
const MODES = ['FEWEST_STEPS', 'STRONGEST_LINKS'] as const;

function readCategories(value: string | null): ConnectionCategory[] {
  const picked = (value ?? '')
    .split(',')
    .filter((c): c is ConnectionCategory =>
      (CATEGORIES as string[]).includes(c),
    );
  return picked.length ? picked : [...DEFAULT_CATEGORIES];
}

/** Copies text, falling back to a hidden text area where the API is missing. */
async function copyText(text: string): Promise<void> {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }
  throw new Error('Clipboard unavailable');
}

/** The path at a glance: portraits joined by lines that carry the kind of each step. */
function Journey({steps, revealed}: {steps: PathStep[]; revealed: number}) {
  const {t} = useI18n();
  const first = steps[0]!.fromArtist;
  return (
    <ol className="cx-journey">
      <JourneyStop artist={first} index={0} shown />
      {steps.map((step, index) => {
        const category = stepCategory(step.evidence);
        const encoding = CATEGORY_ENCODING[category];
        const shown = index < revealed;
        return (
          <li
            key={`${step.toArtist.name}-${index}`}
            className="cx-journey__leg"
            data-shown={shown || undefined}
            style={
              {
                '--line': encoding.color,
                '--line-style': encoding.dash.length ? 'dashed' : 'solid',
              } as CSSProperties
            }
          >
            <span className="cx-journey__link">
              <span className="cx-journey__kind">
                <Swatch category={category} />
                {t('path.step.kind', {
                  kind: t(`category.${category}`),
                  count: step.evidence.length,
                })}
              </span>
            </span>
            <JourneyStop
              artist={step.toArtist}
              index={index + 1}
              shown={shown}
            />
          </li>
        );
      })}
    </ol>
  );
}

function JourneyStop({
  artist,
  index,
  shown,
}: {
  artist: ArtistSummary;
  index: number;
  shown: boolean;
}) {
  const content = (
    <Link className="cx-journey__stop" to={`/artist/${idOf(artist.name)}`}>
      <Portrait
        name={artist.displayName}
        image={imageOf(artist)}
        size="l"
        eager={index < 4}
      />
      <span className="cx-journey__name">
        <bdi>{artist.displayName}</bdi>
      </span>
    </Link>
  );
  // The first stop is its own list item; later stops sit inside their leg.
  return index === 0 ? (
    <li className="cx-journey__start" data-shown={shown || undefined}>
      {content}
    </li>
  ) : (
    content
  );
}

/** One step, with its credits one tap away. */
function StepCard({step, n}: {step: PathStep; n: number}) {
  const {t} = useI18n();
  const [open, setOpen] = useState(false);
  const category = stepCategory(step.evidence);
  const names = useMemo(
    () =>
      new Map([
        [step.fromArtist.name, step.fromArtist.displayName],
        [step.toArtist.name, step.toArtist.displayName],
      ]),
    [step],
  );
  const panelId = `cx-step-${n}`;
  return (
    <li className="cx-step" data-open={open || undefined}>
      <div className="cx-step__head">
        <span className="cx-step__n" aria-hidden="true">
          {n}
        </span>
        <span className="cx-step__pair" aria-hidden="true">
          <Portrait
            name={step.fromArtist.displayName}
            image={imageOf(step.fromArtist)}
            size="s"
          />
          <Portrait
            name={step.toArtist.displayName}
            image={imageOf(step.toArtist)}
            size="s"
          />
        </span>
        <div className="cx-step__text">
          <h4 className="cx-step__title">
            <span className="visually-hidden">{t('path.step', {n})}: </span>
            <bdi>{step.fromArtist.displayName}</bdi>
            <Icon name="chevron" size={18} />
            <bdi>{step.toArtist.displayName}</bdi>
          </h4>
          <p className="cx-step__meta">
            <Swatch category={category} />
            {t('path.step.kind', {
              kind: t(`category.${category}`),
              count: step.evidence.length,
            })}
            {step.track && (
              <>
                {' · '}
                <Link to={songPath(step.track)}>
                  {t('path.step.heardOn', {title: step.track.displayName})}
                </Link>
              </>
            )}
          </p>
        </div>
      </div>
      <button
        type="button"
        className="btn btn--text btn--compact cx-step__toggle"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen(o => !o)}
      >
        <Icon name={open ? 'arrowUp' : 'arrowDown'} />
        {open
          ? t('path.step.hide')
          : t('path.step.more', {count: step.evidence.length})}
      </button>
      <div id={panelId} className="cx-step__credits" hidden={!open}>
        {open && (
          <EvidenceList
            evidence={step.evidence}
            nameOf={name => names.get(name) ?? ''}
          />
        )}
      </div>
    </li>
  );
}

/** The path as a track list: one real recording per step, never claimed as playable here. */
function Mixtape({steps}: {steps: PathStep[]}) {
  const {t} = useI18n();
  const snackbar = useSnackbar();
  const formatList = useListFormat();
  const rows = useMemo(() => mixtapeOf(steps), [steps]);
  const tracks = tracksOf(rows);
  const span = yearSpan(tracks);
  if (tracks.length === 0) return null;
  const from = steps[0]!.fromArtist.displayName;
  const to = steps[steps.length - 1]!.toArtist.displayName;
  const artistsOf = (track: PathTrack) =>
    formatList(track.artists.map(a => a.displayName));
  const text = () =>
    mixtapeText(rows, {
      title: t('path.mixtape.text.title', {from, to}),
      line: (n, track) =>
        track.year
          ? t('path.mixtape.text.lineYear', {
              n,
              title: track.displayName,
              artists: artistsOf(track),
              year: track.year,
            })
          : t('path.mixtape.text.line', {
              n,
              title: track.displayName,
              artists: artistsOf(track),
            }),
      url: window.location.href,
    });
  const collage = tracks
    .flatMap(track => track.artists.slice(0, 1))
    .slice(0, 4);
  let number = 0;

  async function copy() {
    try {
      await copyText(text());
      snackbar(t('path.mixtape.copied'));
    } catch {
      snackbar(t('path.mixtape.copyFailed'));
    }
  }
  async function share() {
    try {
      await navigator.share({
        title: t('path.mixtape.text.title', {from, to}),
        text: text(),
      });
    } catch {
      // The listener closed the share sheet.
    }
  }

  return (
    <section className="cx-mixtape" aria-labelledby="cx-mixtape-title">
      <div className="cx-mixtape__head">
        <div
          className="cx-mixtape__art"
          data-count={collage.length}
          aria-hidden="true"
        >
          {collage.map((artist, index) => (
            <Portrait
              key={`${artist.name}-${index}`}
              name={artist.displayName}
              image={imageOf(artist)}
              size="m"
            />
          ))}
          <span className="cx-mixtape__disc">
            <Icon name="note" />
          </span>
        </div>
        <div className="cx-mixtape__text">
          <p className="cx-overline">
            <Icon name="library" />
            {t('path.mixtape.count', {count: tracks.length})}
            {span &&
              ` · ${
                span.first === span.last
                  ? t('path.mixtape.year', {year: span.first})
                  : t('path.mixtape.years', span)
              }`}
          </p>
          <h3 id="cx-mixtape-title" className="cx-mixtape__title">
            {t('path.mixtape.title')}
          </h3>
          <p className="cx-mixtape__body">{t('path.mixtape.body')}</p>
          <div className="cx-actions">
            <button
              type="button"
              className="btn btn--filled"
              onClick={() => void copy()}
            >
              <Icon name="copy" />
              {t('path.mixtape.copy')}
            </button>
            {typeof navigator.share === 'function' && (
              <button
                type="button"
                className="btn btn--tonal"
                onClick={() => void share()}
              >
                <Icon name="share" />
                {t('path.mixtape.share')}
              </button>
            )}
          </div>
        </div>
      </div>
      <ol className="cx-tracks" aria-label={t('path.mixtape.list')}>
        {rows.map(row => {
          if (!row.track)
            return (
              <li
                key={`step-${row.step}`}
                className="cx-track"
                data-missing="true"
              >
                <span className="cx-track__n" aria-hidden="true">
                  –
                </span>
                <span className="cx-track__gap" aria-hidden="true">
                  <Icon name="link" />
                </span>
                <span className="cx-track__text">
                  <span className="cx-track__note">
                    {t('path.mixtape.noTrack', {
                      from: row.from.displayName,
                      to: row.to.displayName,
                    })}
                  </span>
                </span>
              </li>
            );
          const track = row.track;
          number++;
          return (
            <li key={`step-${row.step}`} className="cx-track">
              <span className="cx-track__n">{number}</span>
              <SongCover song={track} size="s" />
              <span className="cx-track__text">
                <Link className="cx-track__title" to={songPath(track)}>
                  <bdi>{track.displayName}</bdi>
                </Link>
                <span className="cx-track__artists">
                  <bdi>{artistsOf(track)}</bdi>
                  {track.year !== null && (
                    <>
                      {' · '}
                      {t('path.mixtape.year', {year: track.year})}
                    </>
                  )}
                </span>
                <span className="cx-track__why">
                  {t('path.step.label', {
                    n: row.step,
                    from: row.from.displayName,
                    to: row.to.displayName,
                  })}
                  {track.release && (
                    <>
                      {' · '}
                      {t('path.mixtape.fromRelease')}
                    </>
                  )}
                </span>
              </span>
              <ListenLink
                query={trackQuery(track)}
                iconOnly
                label={t('connect.listenToSong', {
                  title: track.displayName,
                  artists: artistsOf(track),
                })}
              />
            </li>
          );
        })}
      </ol>
    </section>
  );
}

function JourneySkeleton() {
  const {t} = useI18n();
  return (
    <div className="cx-result" role="status">
      <span className="visually-hidden">{t('path.loading')}</span>
      <span className="skeleton cx-skel-line" data-w="s" />
      <span className="skeleton cx-skel-line" data-w="l" />
      <div className="cx-journey cx-journey--skeleton" aria-hidden="true">
        {Array.from({length: 4}, (_, i) => (
          <span key={i} className="cx-journey__skel">
            <span className="skeleton cx-skel-portrait" />
            <span className="skeleton cx-skel-line" data-w="xs" />
          </span>
        ))}
      </div>
      {Array.from({length: 3}, (_, i) => (
        <span key={i} className="skeleton cx-skel-row" />
      ))}
    </div>
  );
}

export default function SixDegreesScreen() {
  const {t} = useI18n();
  const snackbar = useSnackbar();
  const [search, setSearch] = useSearchParams();
  const from = search.get('from');
  const to = search.get('to');
  const mode = (
    search.get('mode') === 'STRONGEST_LINKS'
      ? 'STRONGEST_LINKS'
      : 'FEWEST_STEPS'
  ) as PathMode;
  const categories = readCategories(search.get('categories'));
  const [genreFilter, setGenreFilter] = useGenreSelection();
  const [showFilters, setShowFilters] = useState(false);
  const [revealed, setRevealed] = useState(0);
  const starters = useStarterArtists();
  const fromArtist = useArtist(from ?? undefined);
  const toArtist = useArtist(to ?? undefined);
  usePageTitle(t('path.title'));
  useAmbient(fromArtist.data?.displayName ?? null);

  function update(changes: Record<string, string | null>) {
    const next = new URLSearchParams(search);
    for (const [key, value] of Object.entries(changes)) {
      if (value === null || value === '') next.delete(key);
      else next.set(key, value);
    }
    setSearch(next, {replace: true});
  }

  function surprise() {
    const pair = surprisePair(
      starters.map(artist => idOf(artist.name)),
      [from, to],
    );
    if (pair) update({from: pair[0], to: pair[1]});
  }

  const same = from !== null && from === to;
  const path = usePath(
    from && to && !same
      ? {from, to, mode, categories, ...genreFilter, alternatives: 2}
      : null,
  );
  const steps = useMemo(
    () => (path.data?.outcome === 'FOUND' ? path.data.steps : []),
    [path.data],
  );

  // Reveal the journey one step at a time; at once when motion is reduced.
  useEffect(() => {
    const reduce = window.matchMedia(
      '(prefers-reduced-motion: reduce)',
    ).matches;
    if (reduce || steps.length === 0) {
      setRevealed(steps.length);
      return;
    }
    setRevealed(0);
    const timer = window.setInterval(() => {
      setRevealed(n => {
        if (n + 1 >= steps.length) window.clearInterval(timer);
        return Math.min(n + 1, steps.length);
      });
    }, STEP_MS);
    return () => window.clearInterval(timer);
  }, [steps]);

  const chainNames = steps.length
    ? [
        steps[0]!.fromArtist.displayName,
        ...steps.map(s => s.toArtist.displayName),
      ]
    : [];
  const fromName = chainNames[0] ?? fromArtist.data?.displayName ?? '';
  const toName =
    chainNames[chainNames.length - 1] ?? toArtist.data?.displayName ?? '';

  async function shareLink() {
    const url = window.location.href;
    try {
      if (navigator.share) await navigator.share({title: t('path.title'), url});
      else {
        await navigator.clipboard.writeText(url);
        snackbar(t('action.linkCopied'));
      }
    } catch {
      // The listener cancelled the share sheet.
    }
  }

  const loading = path.isFetching && !path.data;
  const notFound =
    path.data?.outcome === 'NOT_CONNECTED_WITHIN_LIMIT' ||
    path.data?.outcome === 'SEARCH_LIMIT_REACHED';

  return (
    <div className="cx cx-path">
      <ToolHero
        overline={t('path.overline')}
        icon="route"
        title={t('path.title')}
        lead={t('path.hero.body')}
      />

      <section className="cx-picker" aria-label={t('path.lead')}>
        <div className="cx-faceoff">
          <ArtistSlot
            label={t('path.from')}
            caption={t('path.pick.from')}
            artist={fromArtist.data}
            loading={Boolean(from) && fromArtist.isPending}
            side="a"
            onPick={id => update({from: id})}
          />
          <div className="cx-faceoff__middle">
            <span className="cx-faceoff__wire" aria-hidden="true" />
            <button
              type="button"
              className="icon-btn icon-btn--outlined cx-swap"
              disabled={!from && !to}
              onClick={() => update({from: to, to: from})}
            >
              <Icon name="swap" label={t('path.swap')} />
            </button>
          </div>
          <ArtistSlot
            label={t('path.to')}
            caption={t('path.pick.to')}
            artist={toArtist.data}
            loading={Boolean(to) && toArtist.isPending}
            side="b"
            onPick={id => update({to: id})}
          />
        </div>
        <div className="cx-picker__bar">
          <div className="cx-seg" role="group" aria-label={t('path.options')}>
            {MODES.map(m => (
              <button
                key={m}
                type="button"
                className="chip"
                aria-pressed={mode === m}
                onClick={() => update({mode: m})}
              >
                {t(`path.mode.${m}`)}
              </button>
            ))}
          </div>
          <div className="cx-actions">
            <button
              type="button"
              className="btn btn--tonal"
              disabled={starters.length < 2}
              onClick={surprise}
            >
              <Icon name="spark" />
              {t('path.surprise')}
            </button>
            <button
              type="button"
              className="icon-btn icon-btn--outlined"
              aria-expanded={showFilters}
              onClick={() => setShowFilters(s => !s)}
            >
              <Icon name="tune" label={t('filter.categories')} />
            </button>
          </div>
        </div>
        {showFilters && (
          <div className="cx-filters">
            <CategoryChips
              value={categories}
              onChange={next => update({categories: next.join(',')})}
            />
            <GenreFilter selection={genreFilter} onChange={setGenreFilter} />
          </div>
        )}
      </section>

      {same && <p className="banner">{t('path.sameArtist')}</p>}

      {!from && !to && (
        <Moment
          icon="route"
          title={t('path.empty.title')}
          body={t('path.empty.body')}
        >
          <button
            type="button"
            className="btn btn--filled"
            disabled={starters.length < 2}
            onClick={surprise}
          >
            <Icon name="spark" />
            {t('path.surprise')}
          </button>
        </Moment>
      )}

      {loading && <JourneySkeleton />}
      {path.isError && (
        <ErrorState error={path.error} onRetry={() => void path.refetch()} />
      )}
      {notFound && (
        <Moment
          icon="route"
          title={
            path.data?.outcome === 'SEARCH_LIMIT_REACHED'
              ? t('path.limitReached')
              : t('path.notConnected', {max: 6})
          }
          body={t('path.notConnected.body')}
          art={
            <span className="cx-moment__pair" aria-hidden="true">
              {fromArtist.data && (
                <Portrait
                  name={fromArtist.data.displayName}
                  image={imageOf(fromArtist.data)}
                  size="l"
                />
              )}
              <span className="cx-moment__gap" />
              {toArtist.data && (
                <Portrait
                  name={toArtist.data.displayName}
                  image={imageOf(toArtist.data)}
                  size="l"
                />
              )}
            </span>
          }
        >
          <button
            type="button"
            className="btn btn--tonal"
            onClick={() =>
              update({
                mode:
                  mode === 'FEWEST_STEPS' ? 'STRONGEST_LINKS' : 'FEWEST_STEPS',
              })
            }
          >
            {t(
              `path.mode.${mode === 'FEWEST_STEPS' ? 'STRONGEST_LINKS' : 'FEWEST_STEPS'}`,
            )}
          </button>
          <button type="button" className="btn btn--tonal" onClick={surprise}>
            <Icon name="spark" />
            {t('path.surprise')}
          </button>
        </Moment>
      )}

      {steps.length > 0 && (
        <section className="cx-result" aria-labelledby="cx-path-result">
          <header className="cx-result__head">
            <div className="cx-result__titles">
              <p className="cx-overline">
                <bdi>
                  {t('path.result.title', {from: fromName, to: toName})}
                </bdi>
              </p>
              <h2 id="cx-path-result" className="cx-result__title">
                {t('path.steps', {count: steps.length})}
              </h2>
              <p className="cx-result__lead">
                {t('path.result.lead', {count: steps.length})}
              </p>
            </div>
            <div className="cx-actions">
              {revealed < steps.length && (
                <button
                  type="button"
                  className="btn btn--text"
                  onClick={() => setRevealed(steps.length)}
                >
                  {t('path.skipAnimation')}
                </button>
              )}
              <button
                type="button"
                className="btn btn--tonal"
                onClick={() => void shareLink()}
              >
                <Icon name="share" />
                {t('action.share')}
              </button>
              <ShareButton
                kind="PATH"
                subjects={[
                  steps[0]!.fromArtist.name,
                  steps[steps.length - 1]!.toArtist.name,
                ]}
                title={t('friends.share.path', {a: fromName, b: toName})}
              />
            </div>
          </header>
          <p className="visually-hidden" aria-live="polite">
            {revealed === steps.length
              ? t('path.announce', {names: chainNames.join(', ')})
              : ''}
          </p>

          <Journey steps={steps} revealed={revealed} />

          <div className="cx-result__grid">
            <section className="cx-section" aria-labelledby="cx-path-steps">
              <h3 id="cx-path-steps" className="cx-section__title">
                {t('path.journey')}
              </h3>
              <ol className="cx-steps">
                {steps.map((step, index) => (
                  <StepCard
                    key={`${step.toArtist.name}-${index}`}
                    step={step}
                    n={index + 1}
                  />
                ))}
              </ol>
              <div className="cx-actions">
                <Link
                  className="btn btn--outlined"
                  to={`/explore/${idOf(steps[0]!.fromArtist.name)}`}
                >
                  <Icon name="explore" />
                  {t('path.openWeb')}
                </Link>
              </div>
            </section>
            <Mixtape steps={steps} />
          </div>

          {path.data &&
            path.data.alternatives.length > 0 &&
            revealed === steps.length && (
              <section className="cx-section" aria-labelledby="cx-path-alt">
                <h3 id="cx-path-alt" className="cx-section__title">
                  {t('path.alternatives')}
                </h3>
                <p className="cx-section__body">
                  {t('path.alternatives.body')}
                </p>
                <ul className="cx-routes">
                  {path.data.alternatives.map(route => (
                    <li
                      key={route.map(a => a.name).join('>')}
                      className="cx-route"
                    >
                      <PortraitChain artists={route} />
                    </li>
                  ))}
                </ul>
              </section>
            )}
        </section>
      )}
    </div>
  );
}
