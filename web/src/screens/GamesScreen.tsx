/**
 * Games hub: today's daily puzzle, a path challenge and the Credit check quiz,
 * with stats kept on this device.
 */
import {useEffect, useState} from 'react';
import {Link, useSearchParams} from 'react-router';

import {idOf} from '../api/client';
import {usePathChallenge} from '../api/discover';
import {usePuzzle} from '../api/queries';
import {useConfigFlags} from '../app/flags';
import {usePageTitle} from '../app/Shell';
import {Icon} from '../components/Icon';
import {Cover} from '../components/Shelf';
import {useI18n} from '../i18n/i18n';
import {CreditCheck} from '../games/CreditCheck';
import {puzzleStatus, type PuzzleStatus} from '../games/status';
import {computeTriviaStats, loadRecords} from '../games/trivia';
import {
  addDays,
  computeStats,
  LAUNCH_DAY,
  loadGames,
  localDate,
  validPuzzleDate,
} from '../play/game';

function storage(): Storage | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

function DailyCard({today}: {today: string}) {
  const {t} = useI18n();
  const puzzle = usePuzzle(today);
  const status: PuzzleStatus = puzzleStatus(loadGames(storage()), today);
  const p = puzzle.data;
  const stateText =
    status.state === 'won'
      ? t('games.daily.state.won', {steps: status.steps})
      : t(`games.daily.state.${status.state}`);
  const action =
    status.state === 'new'
      ? t('games.daily.action.new')
      : status.state === 'playing'
        ? t('games.daily.action.playing')
        : t('games.daily.action.done');
  return (
    <article
      className="game-card game-card--daily"
      aria-labelledby="game-daily"
    >
      <div className="game-card__covers" aria-hidden="true">
        {p && (
          <>
            <Cover name={p.start.displayName} />
            <Cover name={p.target.displayName} />
          </>
        )}
      </div>
      <div className="game-card__body">
        <p className="strapline">{t('games.daily.eyebrow')}</p>
        <h2 id="game-daily">
          {p ? t('games.daily.title', {number: p.number}) : t('play.title')}
        </h2>
        {p && (
          <p>
            {t('games.daily.body', {
              start: p.start.displayName,
              target: p.target.displayName,
              par: p.par,
            })}
          </p>
        )}
        <p className="game-card__meta">
          {p && (
            <span className="chip chip--static">
              {t('games.daily.par', {par: p.par})}
            </span>
          )}
          <span className="chip chip--static" data-state={status.state}>
            {status.state === 'won' && <Icon name="check" size={18} />}
            {stateText}
          </span>
        </p>
        <Link className="btn btn--filled" to="/play">
          <Icon name="play" />
          {action}
        </Link>
      </div>
    </article>
  );
}

function PathCard({today}: {today: string}) {
  const {t} = useI18n();
  const challenge = usePathChallenge(today);
  const c = challenge.data;
  return (
    <article className="game-card" aria-labelledby="game-path">
      <div className="game-card__body">
        <p className="strapline">{t('games.path.eyebrow')}</p>
        <h2 id="game-path">{t('games.path.title')}</h2>
        {c ? (
          <>
            <div className="game-card__pair">
              <Cover name={c.fromArtist.displayName} round />
              <Icon name="route" />
              <Cover name={c.toArtist.displayName} round />
            </div>
            <p>
              {t('games.path.body', {
                from: c.fromArtist.displayName,
                to: c.toArtist.displayName,
                steps: c.steps,
              })}
            </p>
            <Link
              className="btn btn--tonal"
              to={`/six-degrees?from=${idOf(c.fromArtist.name)}&to=${idOf(c.toArtist.name)}`}
            >
              <Icon name="route" />
              {t('games.path.action')}
            </Link>
          </>
        ) : null}
      </div>
    </article>
  );
}

function Stat({label, value}: {label: string; value: string}) {
  return (
    <div className="stat">
      <dd>{value}</dd>
      <dt>{label}</dt>
    </div>
  );
}

function StatsRow({today}: {today: string}) {
  const {t} = useI18n();
  const puzzle = computeStats(loadGames(storage()), today);
  const credit = computeTriviaStats(loadRecords(storage()), today);
  const days = (n: number) =>
    n ? t('games.stats.days', {count: n}) : t('games.stats.none');
  return (
    <section className="section" aria-labelledby="games-stats">
      <h2 id="games-stats" className="section-title">
        {t('games.stats')}
      </h2>
      <dl className="stats">
        <Stat
          label={t('games.stats.puzzleSolved')}
          value={String(puzzle.won)}
        />
        <Stat
          label={t('games.stats.streak')}
          value={days(puzzle.currentStreak)}
        />
        <Stat
          label={t('games.stats.creditPlayed')}
          value={String(credit.played)}
        />
        <Stat
          label={t('games.stats.creditAverage')}
          value={credit.played ? `${credit.average}/5` : t('games.stats.none')}
        />
        <Stat
          label={t('games.stats.creditPerfect')}
          value={String(credit.perfect)}
        />
      </dl>
      <p className="muted">{t('games.stats.note')}</p>
    </section>
  );
}

export default function GamesScreen() {
  const {t} = useI18n();
  const flags = useConfigFlags();
  const [search, setSearch] = useSearchParams();
  const [today, setToday] = useState(() => localDate());
  usePageTitle(t('nav.games'));
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
  const [shown, setShown] = useState(false);
  const [mode, setMode] = useState<'all' | 'daily' | 'credit'>('all');
  useEffect(() => setShown(true), []);
  function go(day: string | null) {
    const next = new URLSearchParams(search);
    if (day && day !== today) next.set('date', day);
    else next.delete('date');
    setSearch(next, {replace: true});
  }

  if (flags.play === false) {
    return (
      <div className="page-header">
        <h1>{t('nav.games')}</h1>
        <p className="lead">{t('games.credit.empty')}</p>
      </div>
    );
  }
  return (
    <div className="stack games" data-ready={shown || undefined}>
      <header className="page-header">
        <p className="strapline">{t('games.strapline')}</p>
        <h1>{t('games.title')}</h1>
        <p className="lead">{t('games.lead')}</p>
      </header>

      <nav className="games-filters" aria-label={t('nav.games')}>
        {(['all', 'daily', 'credit'] as const).map(value => (
          <button
            key={value}
            className="chip"
            aria-pressed={mode === value}
            onClick={() => setMode(value)}
          >
            {t(`games.filter.${value}`)}
          </button>
        ))}
      </nav>

      <div className="games-grid" hidden={mode === 'credit'}>
        <DailyCard today={today} />
        <PathCard today={today} />
      </div>

      <section
        className="section credit-section"
        aria-labelledby="game-credit"
        hidden={mode === 'daily'}
      >
        <p className="strapline">{t('games.credit.eyebrow')}</p>
        <h2 id="game-credit" className="credit-section__title">
          {t('games.credit.title', {number: dayNumber(date)})}
        </h2>
        <nav
          className="row credit-section__nav"
          aria-label={t('games.credit.archive')}
        >
          <button
            className="btn btn--text btn--compact"
            disabled={date <= LAUNCH_DAY}
            onClick={() => go(addDays(date, -1))}
          >
            {t('games.credit.previous')}
          </button>
          <label className="credit-section__date">
            <span className="visually-hidden">{t('games.credit.date')}</span>
            <input
              type="date"
              value={date}
              min={LAUNCH_DAY}
              max={today}
              onChange={e => {
                if (validPuzzleDate(e.target.value, today)) go(e.target.value);
              }}
            />
          </label>
          <button
            className="btn btn--text btn--compact"
            disabled={date >= today}
            onClick={() => go(addDays(date, 1))}
          >
            {t('games.credit.nextDay')}
          </button>
          {date !== today && (
            <button
              className="btn btn--tonal btn--compact"
              onClick={() => go(null)}
            >
              {t('games.credit.today')}
            </button>
          )}
        </nav>
        <CreditCheck date={date} today={today} />
      </section>

      <StatsRow today={today} />
    </div>
  );
}

/** Credit check numbers match the daily puzzle's: 1 on the launch day. */
function dayNumber(date: string): number {
  return (
    Math.round(
      (Date.parse(`${date}T00:00:00Z`) -
        Date.parse(`${LAUNCH_DAY}T00:00:00Z`)) /
        86_400_000,
    ) + 1
  );
}
