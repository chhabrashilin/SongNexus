/**
 * Play (S6, US-04): the daily connection puzzle.
 *
 * Get from the start artist to the target by naming direct collaborators; every
 * correct step shows its credit. Progress lives on this device; the server only
 * checks moves, and a wrong move reveals nothing.
 */
import {useEffect, useRef, useState} from 'react';
import {useSearchParams} from 'react-router';

import {idOf, type ArtistSummary, type Schemas} from '../api/client';
import {
  checkMove,
  getHint,
  reportPuzzleShare,
  useBlockedArtists,
  usePuzzle,
  useReveal,
} from '../api/queries';
import {usePageTitle} from '../app/Shell';
import {useAuth} from '../auth/AuthProvider';
import {Avatar} from '../components/ArtistRow';
import {EvidenceList} from '../components/ConnectionSheet';
import {Icon} from '../components/Icon';
import {SearchBox} from '../components/SearchBox';
import {useSnackbar} from '../components/Snackbar';
import {ErrorState, Spinner} from '../components/States';
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
  saveGame,
  shareText,
  puzzleLink,
  validPuzzleDate,
  stepsLeft,
  undo,
  type GameState,
} from '../play/game';

function storage(): Storage | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

const MOVE_STYLE = {
  closer: 'var(--series-3)',
  same: 'var(--neutral-strong)',
  farther: 'var(--series-2)',
  back: 'var(--neutral-soft)',
} as const;

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
    <div className="stack">
      <nav className="row" aria-label={t('play.archive')}>
        <button
          className="btn btn--text"
          disabled={date <= LAUNCH_DAY}
          onClick={() => navigate(addDays(date, -1))}
        >
          {t('play.previous')}
        </button>
        <label>
          {t('play.date')}{' '}
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
          className="btn btn--text"
          disabled={date >= today}
          onClick={() => navigate(addDays(date, 1))}
        >
          {t('play.nextDay')}
        </button>
        {requested && (
          <button className="btn btn--tonal" onClick={() => navigate(null)}>
            {t('play.today')}
          </button>
        )}
      </nav>
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
  if (puzzle.isPending) return <Spinner />;
  if (puzzle.isError)
    return (
      <ErrorState error={puzzle.error} onRetry={() => void puzzle.refetch()} />
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
  const [miss, setMiss] = useState<string | null>(null);
  const [hints, setHints] = useState<ArtistSummary[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const reveal = useReveal(date, game.status === 'gaveUp');
  useEffect(() => {
    saveGame(game, storage());
  }, [game]);

  const state = game;
  const stats = computeStats(
    [...loadGames(storage()).filter(g => g.date !== date), state],
    today,
  );
  const link = puzzleLink(window.location.origin, date);
  const current = state.chain.length
    ? state.chain[state.chain.length - 1]!.artist
    : p.start;
  const left = stepsLeft(state, p.par);
  const blockedNames = new Set(
    blocked.data?.blockedArtists.map(b => b.name.split('/').pop()) ?? [],
  );
  const involvesBlocked = [p.start, p.target].some(a =>
    blockedNames.has(idOf(a.name)),
  );
  const names = new Map<string, string>([
    [p.start.name, p.start.displayName],
    ...state.chain.map(
      s => [s.artist.name, s.artist.displayName] as [string, string],
    ),
  ]);

  async function move(artist: Pick<ArtistSummary, 'name' | 'displayName'>) {
    if (actionPending.current || state.status !== 'playing') return;
    actionPending.current = true;
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
      } else {
        setGame(g => applyMiss(g));
        setMiss(
          t('play.miss', {
            name: artist.displayName,
            current: current.displayName,
          }),
        );
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

  return (
    <div className="stack" style={{gap: 'var(--space-5)'}}>
      <header className="stack" style={{gap: 'var(--space-2)'}}>
        <span className="muted" style={{font: 'var(--label-large)'}}>
          {t('play.number', {number: p.number})} · {t('play.par', {par: p.par})}
        </span>
        <h1>{t('play.title')}</h1>
        <p>
          {t('play.goal', {
            start: p.start.displayName,
            target: p.target.displayName,
          })}
        </p>
        <p className="muted">{t('play.rules')}</p>
      </header>
      {involvesBlocked && <p className="banner">{t('play.blocked')}</p>}

      <ol className="list" aria-label={t('play.title')}>
        <li className="list-row">
          <Avatar name={p.start.displayName} />
          <span className="list-row__body">
            <span className="list-row__title">
              <bdi>{p.start.displayName}</bdi>
            </span>
          </span>
        </li>
        {state.chain.map((s, i) => (
          <li key={`${s.artist.name}-${i}`} className="stack" style={{gap: 0}}>
            <div
              className="card card--outlined"
              style={{marginInlineStart: 'var(--space-6)'}}
            >
              <EvidenceList
                evidence={s.evidence}
                nameOf={n => names.get(n) ?? ''}
              />
            </div>
            <div className="list-row">
              <Avatar name={s.artist.displayName} />
              <span className="list-row__body">
                <span className="list-row__title">
                  <bdi>{s.artist.displayName}</bdi>
                </span>
                <span className="list-row__subtitle">
                  {s.stepsToTarget === null
                    ? t('play.noRoute', {target: p.target.displayName})
                    : t('play.stepsLeft', {count: s.stepsToTarget})}
                </span>
              </span>
              {state.moves.length > 0 && (
                <span
                  className="badge"
                  style={{
                    borderInlineStart: `4px solid ${MOVE_STYLE[classOf(state, i)]}`,
                  }}
                >
                  {t(`play.move.${classOf(state, i)}`)}
                </span>
              )}
            </div>
          </li>
        ))}
      </ol>

      {state.status === 'playing' && (
        <section className="card stack" aria-busy={busy}>
          <p style={{font: 'var(--title-medium)'}}>
            {t('play.current', {name: current.displayName})}
            {left !== null && ` · ${t('play.stepsLeft', {count: left})}`}
          </p>
          <fieldset
            disabled={busy}
            style={{border: 0, padding: 0, margin: 0, minInlineSize: 0}}
          >
            <SearchBox
              key={current.name}
              label={t('play.next', {name: current.displayName})}
              placeholder={t('play.next', {name: current.displayName})}
              types={['ARTIST']}
              onPick={result => void move(result)}
            />
          </fieldset>
          <p aria-live="polite" className={miss ? 'banner' : 'visually-hidden'}>
            {miss ?? ''}
          </p>
          {Boolean(error) && <ErrorState error={error} />}
          {hints.length > 0 && (
            <div className="stack" style={{gap: 'var(--space-2)'}}>
              <span>{t('play.hint.lead')}</span>
              <div className="chips">
                {hints.map(h => (
                  <button
                    key={h.name}
                    type="button"
                    className="chip"
                    disabled={busy}
                    onClick={() => void move(h)}
                  >
                    {h.displayName}
                  </button>
                ))}
              </div>
            </div>
          )}
          <div className="row">
            <button
              type="button"
              className="btn btn--tonal"
              disabled={busy}
              onClick={() => void askHint()}
            >
              {t('play.hint')}
            </button>
            <button
              type="button"
              className="btn btn--text"
              disabled={busy || state.chain.length === 0}
              onClick={() => {
                setGame(g => undo(g));
                setHints([]);
                setMiss(null);
                setError(null);
              }}
            >
              <Icon name="back" />
              {t('play.undo')}
            </button>
            <button
              type="button"
              className="btn btn--text"
              disabled={busy}
              onClick={() => setGame(g => giveUp(g, localDate()))}
            >
              {t('play.giveUp')}
            </button>
          </div>
        </section>
      )}

      {state.status === 'won' && (
        <section className="card stack" role="status">
          <h2>{t('play.won', {count: state.chain.length, par: p.par})}</h2>
          <pre
            style={{
              font: 'var(--body-large)',
              margin: 0,
              whiteSpace: 'pre-wrap',
            }}
          >
            {shareText(state, p, t, link)}
          </pre>
          <button
            type="button"
            className="btn btn--filled"
            onClick={() => void share()}
          >
            <Icon name="share" />
            {t('play.share')}
          </button>
          <p className="muted">{t('play.comeBack')}</p>
        </section>
      )}

      {state.status === 'gaveUp' && (
        <section className="card stack">
          <h2>{t('play.gaveUp')}</h2>
          <pre
            style={{
              font: 'var(--body-large)',
              margin: 0,
              whiteSpace: 'pre-wrap',
              overflowWrap: 'anywhere',
            }}
          >
            {shareText(state, p, t, link)}
          </pre>
          {reveal.isPending && <Spinner />}
          {reveal.isError && (
            <ErrorState
              error={reveal.error}
              onRetry={() => void reveal.refetch()}
            />
          )}
          {reveal.data?.steps.map(step => (
            <div
              key={step.toArtist.name}
              className="stack"
              style={{gap: 'var(--space-1)'}}
            >
              <strong>
                <bdi>{step.fromArtist.displayName}</bdi> →{' '}
                <bdi>{step.toArtist.displayName}</bdi>
              </strong>
              <EvidenceList
                evidence={step.evidence}
                nameOf={n =>
                  n === step.fromArtist.name
                    ? step.fromArtist.displayName
                    : step.toArtist.displayName
                }
              />
            </div>
          ))}
          <button
            type="button"
            className="btn btn--tonal"
            onClick={() => void share()}
          >
            <Icon name="share" />
            {t('play.share')}
          </button>
          <p className="muted">{t('play.comeBack')}</p>
        </section>
      )}
      <section className="card stack" aria-label={t('play.stats')}>
        <h2>{t('play.stats')}</h2>
        <dl className="play-stats">
          {(
            [
              'played',
              'winRate',
              'perfect',
              'currentStreak',
              'maxStreak',
            ] as const
          ).map(key => (
            <div key={key}>
              <dt>{t(`play.stats.${key}`)}</dt>
              <dd>
                {stats[key]}
                {key === 'winRate' ? '%' : ''}
              </dd>
            </div>
          ))}
        </dl>
        <p className="muted">{t('play.stats.note')}</p>
      </section>
    </div>
  );
}

/** The move that produced chain step i (moves also include "back" entries). */
function classOf(
  state: GameState,
  index: number,
): 'closer' | 'same' | 'farther' {
  // Replay moves: each non-"back" move pushes a step, each "back" pops one.
  const stack: ('closer' | 'same' | 'farther')[] = [];
  for (const m of state.moves) {
    if (m === 'back') stack.pop();
    else stack.push(m);
  }
  return stack[index] ?? 'same';
}
