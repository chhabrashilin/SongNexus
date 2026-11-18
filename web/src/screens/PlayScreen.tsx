/**
 * Play (S6, US-04): the daily connection puzzle.
 *
 * Get from the start artist to the target by naming direct collaborators; every
 * correct step shows its credit. The route grows on a board of portraits, with
 * an empty place for each step still needed. Progress lives on this device; the
 * server only checks moves, and a wrong move reveals nothing.
 */
import {useEffect, useRef, useState, type CSSProperties} from 'react';
import {Link, useSearchParams} from 'react-router';

import {
  idOf,
  type ArtistSummary,
  type Evidence,
  type Schemas,
} from '../api/client';
import {
  checkMove,
  getHint,
  reportPuzzleShare,
  useBlockedArtists,
  usePuzzle,
  useReveal,
} from '../api/queries';
import {useAmbient} from '../app/ambient';
import {usePageTitle} from '../app/Shell';
import {useAuth} from '../auth/AuthProvider';
import {Avatar, imageOf} from '../components/ArtistRow';
import {EvidenceList} from '../components/ConnectionSheet';
import {Icon} from '../components/Icon';
import {SearchBox} from '../components/SearchBox';
import {Cover} from '../components/Shelf';
import {useSnackbar} from '../components/Snackbar';
import {ErrorState} from '../components/States';
import {Confetti} from '../games/Confetti';
import {Leaderboards, ScoreSubmit} from '../games/Leaderboard';
import {puzzleMoves} from '../games/scores';
import {useI18n} from '../i18n/i18n';
import {
  applyHint,
  addDays,
  applyMiss,
  applyStep,
  giveUp,
  computeStats,
  LAUNCH_DAY,
  loadGame,
  loadGames,
  localDate,
  openSlots,
  saveGame,
  shareText,
  puzzleLink,
  validPuzzleDate,
  stepMoves,
  stepsLeft,
  undo,
} from '../play/game';

function storage(): Storage | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

type Person = Pick<ArtistSummary, 'name' | 'displayName'>;

export default function PlayScreen() {
  const {t} = useI18n();
  const [search, setSearch] = useSearchParams();
  const [today, setToday] = useState(() => localDate());
  usePageTitle(t('play.title'));
  useEffect(() => {
    const update = () => setToday(localDate());
    const timer = window.setInterval(update, 30_000);
    window.addEventListener('focus', update);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener('focus', update);
    };
  }, []);
  const requested = search.get('date');
  const date =
    requested && validPuzzleDate(requested, today) ? requested : today;
  function navigate(day: string | null) {
    const next = new URLSearchParams(search);
    if (day) next.set('date', day);
    else next.delete('date');
    setSearch(next);
  }
  return (
    <div className="play">
      <div className="play__bar">
        <Link className="btn btn--text btn--compact play__back" to="/games">
          <Icon name="back" />
          {t('nav.games')}
        </Link>
        <nav className="play-archive glass" aria-label={t('play.archive')}>
          <button
            type="button"
            className="btn btn--text btn--compact"
            disabled={date <= LAUNCH_DAY}
            onClick={() => navigate(addDays(date, -1))}
          >
            <Icon name="chevronStart" />
            <span className="play-archive__label">{t('play.previous')}</span>
          </button>
          <label className="play-archive__date">
            <span className="visually-hidden">{t('play.date')}</span>
            <Icon name="calendar" size={18} />
            <input
              type="date"
              value={date}
              min={LAUNCH_DAY}
              max={today}
              onChange={e => {
                if (validPuzzleDate(e.target.value, today))
                  navigate(e.target.value);
              }}
            />
          </label>
          <button
            type="button"
            className="btn btn--text btn--compact"
            disabled={date >= today}
            onClick={() => navigate(addDays(date, 1))}
          >
            <span className="play-archive__label">{t('play.nextDay')}</span>
            <Icon name="chevron" />
          </button>
          {requested && (
            <button
              type="button"
              className="btn btn--tonal btn--compact"
              onClick={() => navigate(null)}
            >
              {t('play.today')}
            </button>
          )}
        </nav>
      </div>
      {requested && !validPuzzleDate(requested, today) && (
        <p className="banner" role="status">
          {t('play.invalidDate')}
        </p>
      )}
      <PuzzleLoader date={date} today={today} />
    </div>
  );
}

function PuzzleLoader({date, today}: {date: string; today: string}) {
  const puzzle = usePuzzle(date);
  if (puzzle.isPending) return <PlaySkeleton />;
  if (puzzle.isError)
    return (
      <div className="play-hero play-hero--state">
        <ErrorState
          error={puzzle.error}
          onRetry={() => void puzzle.refetch()}
        />
      </div>
    );
  const p = puzzle.data;
  const puzzleKey = `${p.graphVersion}:${p.start.name}:${p.target.name}:${p.par}`;
  return (
    <DailyPuzzle
      key={`${date}:${puzzleKey}`}
      p={p}
      today={today}
      puzzleKey={puzzleKey}
    />
  );
}

function PlaySkeleton() {
  const {t} = useI18n();
  useAmbient(null);
  return (
    <div className="play-hero" role="status">
      <span className="visually-hidden">{t('state.loading')}</span>
      <div className="play-hero__text" aria-hidden="true">
        <span className="skeleton play-skel play-skel--chip" />
        <span className="skeleton play-skel play-skel--title" />
        <span className="skeleton play-skel play-skel--line" />
      </div>
      <div className="play-board play-board--skeleton" aria-hidden="true">
        <span className="skeleton play-skel--portrait" />
        <span className="skeleton play-skel--slot" />
        <span className="skeleton play-skel--slot" />
        <span className="skeleton play-skel--portrait" />
      </div>
    </div>
  );
}

const MOVE_HUE = {
  closer: 'var(--series-3)',
  same: 'var(--neutral-strong)',
  farther: 'var(--series-2)',
} as const;

function DailyPuzzle({
  p,
  today,
  puzzleKey,
}: {
  p: Schemas['Puzzle'];
  today: string;
  puzzleKey: string;
}) {
  const {t} = useI18n();
  const snackbar = useSnackbar();
  const auth = useAuth();
  const date = p.date;
  const blocked = useBlockedArtists(auth.status === 'signedIn');
  const [game, setGame] = useState(() =>
    loadGame(date, p.graphVersion, storage(), puzzleKey),
  );
  const actionPending = useRef(false);
  const [miss, setMiss] = useState<{text: string; n: number} | null>(null);
  const [hints, setHints] = useState<ArtistSummary[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  // Set when this visit's move solved it (not when a finished game reloads).
  const [celebrate, setCelebrate] = useState(false);
  const [interacted, setInteracted] = useState(false);
  const outcome = useRef<HTMLHeadingElement>(null);
  const board = useRef<HTMLOListElement>(null);
  const reveal = useReveal(date, game.status === 'gaveUp');
  useAmbient(p.target.displayName);
  useEffect(() => {
    saveGame(game, storage());
  }, [game]);

  const state = game;
  const stats = computeStats(
    [...loadGames(storage()).filter(g => g.date !== date), state],
    today,
  );
  const link = puzzleLink(window.location.origin, date);
  const current: Person = state.chain.length
    ? state.chain[state.chain.length - 1]!.artist
    : p.start;
  const left = stepsLeft(state, p.par);
  const moves = stepMoves(state);
  const slots = openSlots(state, p.par);
  const blockedNames = new Set(
    blocked.data?.blockedArtists.map(b => b.name.split('/').pop()) ?? [],
  );
  const involvesBlocked = [p.start, p.target].some(a =>
    blockedNames.has(idOf(a.name)),
  );
  const names = new Map<string, string>([
    [p.start.name, p.start.displayName],
    [p.target.name, p.target.displayName],
    ...state.chain.map(
      s => [s.artist.name, s.artist.displayName] as [string, string],
    ),
  ]);
  const solvedOnBoard = state.status === 'won';

  // Keep the newest step in view on a narrow board.
  useEffect(() => {
    const el = board.current;
    if (!el) return;
    const last = el.querySelector<HTMLElement>('[data-current]');
    last?.scrollIntoView?.({block: 'nearest', inline: 'center'});
  }, [state.chain.length]);
  // A finished game moves focus to its outcome.
  useEffect(() => {
    if (interacted && state.status !== 'playing') outcome.current?.focus();
  }, [interacted, state.status]);

  async function move(artist: Person) {
    if (actionPending.current || state.status !== 'playing') return;
    actionPending.current = true;
    setInteracted(true);
    setBusy(true);
    setMiss(null);
    setHints([]);
    setError(null);
    try {
      const result = await checkMove(date, current.name, artist.name);
      if (result.connected && result.artist) {
        const step = {
          artist: result.artist,
          evidence: result.evidence,
          stepsToTarget: result.stepsToTarget,
        };
        setGame(g =>
          applyStep(g, step, p.par, result.reachedTarget, localDate()),
        );
        if (result.reachedTarget) setCelebrate(true);
      } else {
        setGame(g => applyMiss(g));
        setMiss(m => ({
          text: t('play.miss', {
            name: artist.displayName,
            current: current.displayName,
          }),
          n: (m?.n ?? 0) + 1,
        }));
      }
    } catch (e) {
      setError(e);
    } finally {
      actionPending.current = false;
      setBusy(false);
    }
  }

  async function askHint() {
    if (actionPending.current || state.status !== 'playing') return;
    actionPending.current = true;
    setInteracted(true);
    setBusy(true);
    setError(null);
    try {
      const candidates = (await getHint(date, current.name)).candidates;
      setHints(candidates);
      if (candidates.length) setGame(g => applyHint(g));
      else snackbar(t('play.hint.empty'));
    } catch (e) {
      setError(e);
    } finally {
      actionPending.current = false;
      setBusy(false);
    }
  }

  async function share() {
    const text = shareText(state, p, t, link);
    try {
      if (navigator.share) await navigator.share({text});
      else {
        await navigator.clipboard.writeText(text);
        snackbar(t('play.shareCopied'));
      }
      void reportPuzzleShare().catch(() => {});
    } catch (e) {
      if (!(e instanceof DOMException && e.name === 'AbortError'))
        snackbar(t('play.shareFailed'));
    }
  }

  const moveNames = puzzleMoves(p.start, state);
  const submission = moveNames
    ? {game: 'PUZZLE' as const, date, moves: moveNames}
    : null;

  const route = state.chain.map((s, i) => ({
    from: i === 0 ? p.start : state.chain[i - 1]!.artist,
    to: s.artist,
    evidence: s.evidence,
  }));

  return (
    <>
      {celebrate && <Confetti />}
      <section className="play-hero" aria-labelledby="play-title">
        <div className="play-hero__text">
          <p className="play-hero__overline">
            <Icon name="puzzle" size={16} />
            {t('play.number', {number: p.number})}
            <span aria-hidden="true">·</span>
            {t('play.par', {par: p.par})}
          </p>
          <h1 id="play-title">{t('play.title')}</h1>
          <p className="play-hero__goal">
            <bdi>
              {t('play.goal', {
                start: p.start.displayName,
                target: p.target.displayName,
              })}
            </bdi>
          </p>
          <details className="more">
            <summary>{t('play.howTo')}</summary>
            <div className="more__body">
              <p>{t('play.rules')}</p>
              <p>{t('play.rules.colors')}</p>
            </div>
          </details>
        </div>

        <ol
          ref={board}
          className="play-board"
          aria-label={t('play.board')}
          data-status={state.status}
        >
          <BoardNode
            person={p.start}
            kind="start"
            caption={t('play.board.start')}
            current={state.status === 'playing' && state.chain.length === 0}
          />
          {state.chain.map((s, i) => {
            const isTarget = solvedOnBoard && i === state.chain.length - 1;
            return (
              <BoardNode
                key={`${s.artist.name}-${i}`}
                person={s.artist}
                kind={isTarget ? 'target' : 'step'}
                move={moves[i]}
                caption={
                  isTarget
                    ? t('play.board.target')
                    : t(`play.move.${moves[i] ?? 'same'}`)
                }
                current={
                  state.status === 'playing' && i === state.chain.length - 1
                }
              />
            );
          })}
          {Array.from({length: slots}, (_, i) => (
            <li
              key={`slot-${i}`}
              className="play-node"
              data-kind="slot"
              aria-hidden="true"
            >
              <span className="play-link" />
              <span className="play-node__slot">?</span>
            </li>
          ))}
          {!solvedOnBoard && (
            <BoardNode
              person={p.target}
              kind="target"
              caption={t('play.board.target')}
              gap={state.status === 'playing' && left === null}
            />
          )}
        </ol>
      </section>

      {involvesBlocked && <p className="banner">{t('play.blocked')}</p>}

      {state.status === 'playing' && (
        <section
          className="play-turn"
          aria-busy={busy}
          aria-labelledby="play-turn-title"
        >
          <div className="play-turn__head">
            <Avatar name={current.displayName} image={imageOf(current)} />
            <p className="play-turn__title" id="play-turn-title">
              <bdi>{t('play.current', {name: current.displayName})}</bdi>
            </p>
            <span className="play-turn__left">
              {left === null
                ? t('play.noRoute', {target: p.target.displayName})
                : t('play.stepsLeft', {count: left})}
            </span>
          </div>
          <fieldset disabled={busy} className="play-turn__search">
            <SearchBox
              key={current.name}
              label={t('play.next', {name: current.displayName})}
              placeholder={t('play.next', {name: current.displayName})}
              types={['ARTIST']}
              autoFocus={interacted}
              onPick={result => void move(result)}
            />
          </fieldset>
          <p
            aria-live="polite"
            className={miss ? 'play-miss' : 'visually-hidden'}
          >
            {miss && (
              // Keyed so the nudge replays on every miss.
              <span key={miss.n} className="play-miss__text">
                <Icon name="close" size={18} />
                {miss.text}
              </span>
            )}
          </p>
          {Boolean(error) && <ErrorState error={error} />}
          {hints.length > 0 && (
            <div className="play-hints">
              <p className="play-hints__lead">
                <Icon name="lightbulb" size={18} />
                {t('play.hint.lead')}
              </p>
              <ul className="play-hints__list">
                {hints.map(h => (
                  <li key={h.name}>
                    <button
                      type="button"
                      className="play-hint"
                      disabled={busy}
                      onClick={() => void move(h)}
                    >
                      <Avatar name={h.displayName} image={imageOf(h)} />
                      <bdi>{h.displayName}</bdi>
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}
          <div className="play-turn__tools">
            <button
              type="button"
              className="btn btn--tonal"
              disabled={busy}
              onClick={() => void askHint()}
            >
              <Icon name="lightbulb" />
              {t('play.hint')}
            </button>
            <button
              type="button"
              className="btn btn--text"
              disabled={busy || state.chain.length === 0}
              onClick={() => {
                setInteracted(true);
                setGame(g => undo(g));
                setHints([]);
                setMiss(null);
                setError(null);
              }}
            >
              <Icon name="undo" />
              {t('play.undo')}
            </button>
            <button
              type="button"
              className="btn btn--text play-turn__give-up"
              disabled={busy}
              onClick={() => {
                setInteracted(true);
                setGame(g => giveUp(g, localDate()));
              }}
            >
              <Icon name="flag" />
              {t('play.giveUp')}
            </button>
          </div>
        </section>
      )}

      {state.status === 'won' && (
        <section
          className="play-result play-result--won"
          aria-labelledby="play-won"
        >
          <span className="play-result__badge" aria-hidden="true">
            <Icon name="trophy" size={32} />
          </span>
          <h2 id="play-won" ref={outcome} tabIndex={-1}>
            {t('play.won', {count: state.chain.length, par: p.par})}
          </h2>
          <p className="play-result__sub">
            {state.chain.length <= p.par
              ? t('play.won.perfect')
              : t('play.won.over', {count: state.chain.length - p.par})}
            {stats.currentStreak > 0 && (
              <>
                {' '}
                <span className="play-result__streak">
                  <Icon name="fire" size={18} />
                  {t('games.stats.days', {count: stats.currentStreak})}
                </span>
              </>
            )}
          </p>
          <ShareCard text={shareText(state, p, t, link)} onShare={share} />
          <p className="muted">{t('play.comeBack')}</p>
          <ScoreSubmit
            game="PUZZLE"
            date={date}
            today={today}
            play={submission}
          />
          <NextUp />
        </section>
      )}

      {state.status === 'gaveUp' && (
        <section className="play-result" aria-labelledby="play-reveal">
          <h2 id="play-reveal" ref={outcome} tabIndex={-1}>
            {t('play.gaveUp')}
          </h2>
          {reveal.isPending && (
            <div className="play-route" role="status">
              <span className="visually-hidden">{t('state.loading')}</span>
              <span className="skeleton play-skel play-skel--line" />
              <span className="skeleton play-skel play-skel--line" />
            </div>
          )}
          {reveal.isError && (
            <ErrorState
              error={reveal.error}
              onRetry={() => void reveal.refetch()}
            />
          )}
          {reveal.data && (
            <RouteSteps
              steps={reveal.data.steps.map(s => ({
                from: s.fromArtist,
                to: s.toArtist,
                evidence: s.evidence,
              }))}
            />
          )}
          <ShareCard text={shareText(state, p, t, link)} onShare={share} />
          <ScoreSubmit game="PUZZLE" date={date} today={today} play={null} />
          <p className="muted">{t('play.comeBack')}</p>
          <NextUp />
        </section>
      )}

      {state.status !== 'playing' && (
        <Leaderboards game="PUZZLE" date={date} placement="result" />
      )}

      {route.length > 0 && state.status !== 'gaveUp' && (
        <section className="play-section" aria-labelledby="play-route">
          <h2 id="play-route" className="play-section__title">
            {t('play.route.title')}
          </h2>
          <RouteSteps steps={route} names={names} />
        </section>
      )}

      <section className="play-section" aria-label={t('play.stats')}>
        <h2 className="play-section__title">{t('play.stats')}</h2>
        <dl className="stats play-stats">
          {(
            [
              'played',
              'winRate',
              'perfect',
              'currentStreak',
              'maxStreak',
            ] as const
          ).map(key => (
            <div key={key} className="stat">
              <dt className="stat__label">{t(`play.stats.${key}`)}</dt>
              <dd className="stat__value">
                {stats[key]}
                {key === 'winRate' ? '%' : ''}
              </dd>
            </div>
          ))}
        </dl>
        <p className="muted play-section__note">{t('play.stats.note')}</p>
      </section>
    </>
  );
}

function BoardNode({
  person,
  kind,
  caption,
  move,
  current = false,
  gap = false,
}: {
  person: Person;
  kind: 'start' | 'step' | 'target';
  caption: string;
  move?: 'closer' | 'same' | 'farther' | undefined;
  current?: boolean;
  /** No route from the current artist to here: draw the link broken. */
  gap?: boolean;
}) {
  return (
    <li
      className="play-node"
      data-kind={kind}
      data-current={current || undefined}
      data-move={move}
      style={move ? ({'--move': MOVE_HUE[move]} as CSSProperties) : undefined}
    >
      {kind !== 'start' && (
        <span className="play-link" data-gap={gap || undefined} />
      )}
      <span className="play-node__body">
        <Cover name={person.displayName} image={imageOf(person)} round eager />
        <span className="play-node__name">
          <bdi>{person.displayName}</bdi>
        </span>
        <span className="play-node__caption">{caption}</span>
      </span>
    </li>
  );
}

function RouteSteps({
  steps,
  names,
}: {
  steps: {from: Person; to: Person; evidence: Evidence[]}[];
  names?: Map<string, string>;
}) {
  return (
    <ol className="play-route">
      {steps.map((step, i) => (
        <li key={`${step.to.name}-${i}`} className="play-route__step">
          <div className="play-route__pair">
            <Avatar name={step.from.displayName} image={imageOf(step.from)} />
            <Icon name="chevron" size={18} />
            <Avatar name={step.to.displayName} image={imageOf(step.to)} />
            <strong>
              <bdi>{step.from.displayName}</bdi> →{' '}
              <bdi>{step.to.displayName}</bdi>
            </strong>
          </div>
          <EvidenceList
            evidence={step.evidence}
            nameOf={n =>
              names?.get(n) ??
              (n === step.from.name
                ? step.from.displayName
                : n === step.to.name
                  ? step.to.displayName
                  : '')
            }
          />
        </li>
      ))}
    </ol>
  );
}

/** The spoiler-free result, as it will be shared, and the share button. */
function ShareCard({text, onShare}: {text: string; onShare: () => void}) {
  const {t} = useI18n();
  return (
    <div className="play-share">
      <pre className="play-share__text">{text}</pre>
      <button type="button" className="btn btn--filled" onClick={onShare}>
        <Icon name="share" />
        {t('play.share')}
      </button>
    </div>
  );
}

/** What else is new today, once the puzzle is done. */
function NextUp() {
  const {t} = useI18n();
  return (
    <div className="play-next">
      <Link className="btn btn--tonal" to="/games#credit-check">
        <Icon name="quiz" />
        {t('play.next.credit')}
      </Link>
      <Link className="btn btn--tonal" to="/stories">
        <Icon name="movie" />
        {t('play.next.stories')}
      </Link>
    </div>
  );
}
