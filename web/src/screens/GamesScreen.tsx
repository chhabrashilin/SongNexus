/**
 * Games hub: today first. A hero with the streak and today's three games (the
 * daily puzzle, Credit check and the path challenge) and where each stands,
 * the week at a glance, Credit check itself, the leaderboards and the stats
 * kept on this device. Every game has an archive back to launch day.
 */
import {useCallback, useEffect, useState, type CSSProperties} from 'react';
import {Link, useLocation, useSearchParams} from 'react-router';

import {idOf, type ArtistSummary} from '../api/client';
import {usePathChallenge, useTrivia} from '../api/discover';
import {usePuzzle} from '../api/queries';
import {useAmbient} from '../app/ambient';
import {useConfigFlags} from '../app/flags';
import {usePageTitle} from '../app/Shell';
import {imageOf} from '../components/ArtistRow';
import {Icon} from '../components/Icon';
import {Cover, hueOf} from '../components/Shelf';
import {CreditCheck} from '../games/CreditCheck';
import {Leaderboards} from '../games/Leaderboard';
import {
  archiveDays,
  creditStatus,
  finishedToday,
  puzzleStatus,
} from '../games/status';
import {computeTriviaStats, loadRecords} from '../games/trivia';
import {useI18n} from '../i18n/i18n';
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

function useToday(): string {
  const [today, setToday] = useState(() => localDate());
  useEffect(() => {
    const update = () => setToday(localDate());
    const timer = window.setInterval(update, 30_000);
    window.addEventListener('focus', update);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener('focus', update);
    };
  }, []);
  return today;
}

/** A calendar date in the reader's language ("Tuesday, November 17"). */
function useDateFormat() {
  const {locale} = useI18n();
  return useCallback(
    (date: string, options: Intl.DateTimeFormatOptions) => {
      const tag = locale === 'ar-XB' ? 'ar' : 'en-US';
      return new Intl.DateTimeFormat(tag, {...options, timeZone: 'UTC'}).format(
        new Date(`${date}T00:00:00Z`),
      );
    },
    [locale],
  );
}

/** Two people joined by a dashed line: the ends of a puzzle or a path. */
function Pair({
  from,
  to,
  eager = false,
}: {
  from: ArtistSummary;
  to: ArtistSummary;
  eager?: boolean;
}) {
  return (
    <span className="today-pair" aria-hidden="true">
      <Cover
        name={from.displayName}
        image={imageOf(from)}
        round
        eager={eager}
      />
      <span className="today-pair__link" />
      <Cover name={to.displayName} image={imageOf(to)} round eager={eager} />
    </span>
  );
}

function PuzzleTile({today}: {today: string}) {
  const {t} = useI18n();
  const puzzle = usePuzzle(today);
  const status = puzzleStatus(loadGames(storage()), today);
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
      className="today-tile today-tile--puzzle"
      aria-labelledby="today-puzzle"
      style={
        {'--hue': hueOf(p?.target.displayName ?? 'puzzle')} as CSSProperties
      }
    >
      <div className="today-tile__art">
        {p ? (
          <Pair from={p.start} to={p.target} eager />
        ) : (
          <span className="today-pair" aria-hidden="true">
            <span className="skeleton today-skel--portrait" />
            <span className="today-pair__link" />
            <span className="skeleton today-skel--portrait" />
          </span>
        )}
      </div>
      <div className="today-tile__body">
        <p className="today-tile__eyebrow">
          <Icon name="puzzle" size={16} />
          {p
            ? t('games.daily.title', {number: p.number})
            : t('games.daily.eyebrow')}
        </p>
        <h2 id="today-puzzle" className="today-tile__title">
          {p ? (
            <bdi>
              {t('home.stage.puzzle.title', {
                start: p.start.displayName,
                target: p.target.displayName,
              })}
            </bdi>
          ) : (
            t('play.title')
          )}
        </h2>
        <p className="today-tile__meta">
          {p && (
            <span className="today-chip">
              {t('games.daily.par', {par: p.par})}
            </span>
          )}
          <span className="today-chip" data-state={status.state}>
            {status.state === 'won' && <Icon name="check" size={16} />}
            {stateText}
          </span>
        </p>
        <Link
          className={
            status.state === 'new' || status.state === 'playing'
              ? 'btn btn--filled'
              : 'btn btn--tonal'
          }
          to="/play"
        >
          <Icon name="play" />
          {action}
        </Link>
      </div>
    </article>
  );
}

function CreditTile({today, version}: {today: string; version: number}) {
  const {t} = useI18n();
  const quiz = useTrivia(today);
  void version;
  const status = creditStatus(loadRecords(storage()), today);
  const faces = quiz.data?.questions.map(q => q.artist) ?? [];
  const total = quiz.data?.questions.length ?? 5;
  const stateText =
    status.state === 'new'
      ? t('games.credit.state.new')
      : status.state === 'playing'
        ? t('games.credit.state.playing', {
            answered: status.answered,
            total: status.total,
          })
        : t('games.credit.state.done', {
            score: status.score,
            total: status.total,
          });
  return (
    <article
      className="today-tile today-tile--credit"
      aria-labelledby="today-credit"
      style={
        {'--hue': hueOf(faces[0]?.displayName ?? 'credit')} as CSSProperties
      }
    >
      <div className="today-tile__art">
        <span className="today-faces" aria-hidden="true">
          {faces.length
            ? faces
                .slice(0, 5)
                .map((artist, i) => (
                  <Cover
                    key={`${artist.name}-${i}`}
                    name={artist.displayName}
                    image={imageOf(artist)}
                    round
                  />
                ))
            : Array.from({length: 4}, (_, i) => (
                <span key={i} className="skeleton today-skel--face" />
              ))}
        </span>
      </div>
      <div className="today-tile__body">
        <p className="today-tile__eyebrow">
          <Icon name="quiz" size={16} />
          {t('games.credit.eyebrow')}
        </p>
        <h2 id="today-credit" className="today-tile__title">
          {t('games.credit.card.body', {count: total})}
        </h2>
        <p className="today-tile__meta">
          <span
            className="today-chip"
            data-state={status.state === 'done' ? 'won' : status.state}
          >
            {status.state === 'done' && <Icon name="check" size={16} />}
            {stateText}
          </span>
        </p>
        <a
          className={
            status.state === 'done' ? 'btn btn--tonal' : 'btn btn--filled'
          }
          href="#credit-check"
          onClick={event => {
            event.preventDefault();
            const target = document.getElementById('credit-check');
            target?.scrollIntoView({block: 'start'});
            target
              ?.querySelector<HTMLElement>('button, h2')
              ?.focus({preventScroll: true});
          }}
        >
          <Icon name="quiz" />
          {status.state === 'new'
            ? t('games.credit.action.new')
            : status.state === 'playing'
              ? t('games.credit.action.playing')
              : t('games.credit.action.done')}
        </a>
      </div>
    </article>
  );
}

function PathTile({today}: {today: string}) {
  const {t} = useI18n();
  const challenge = usePathChallenge(today);
  const c = challenge.data;
  if (challenge.isError) return null;
  return (
    <article
      className="today-tile today-tile--path"
      aria-labelledby="today-path"
      style={
        {'--hue': hueOf(c?.fromArtist.displayName ?? 'path')} as CSSProperties
      }
    >
      <div className="today-tile__art">
        {c ? (
          <Pair from={c.fromArtist} to={c.toArtist} />
        ) : (
          <span className="today-pair" aria-hidden="true">
            <span className="skeleton today-skel--portrait" />
            <span className="today-pair__link" />
            <span className="skeleton today-skel--portrait" />
          </span>
        )}
      </div>
      <div className="today-tile__body">
        <p className="today-tile__eyebrow">
          <Icon name="route" size={16} />
          {t('games.path.eyebrow')}
        </p>
        <h2 id="today-path" className="today-tile__title">
          {c ? (
            <bdi>
              {t('games.path.body', {
                from: c.fromArtist.displayName,
                to: c.toArtist.displayName,
                steps: c.steps,
              })}
            </bdi>
          ) : (
            t('games.path.title')
          )}
        </h2>
        <p className="today-tile__note">{t('games.path.hint')}</p>
        {c && (
          <Link
            className="btn btn--tonal"
            to={`/six-degrees?from=${idOf(c.fromArtist.name)}&to=${idOf(c.toArtist.name)}`}
          >
            <Icon name="route" />
            {t('games.path.action')}
          </Link>
        )}
      </div>
    </article>
  );
}

/** The last seven days: each one's puzzle state, a link into the archive. */
function WeekStrip({today}: {today: string}) {
  const {t} = useI18n();
  const format = useDateFormat();
  const days = archiveDays(loadGames(storage()), today, 7);
  return (
    <nav className="week" aria-label={t('games.week.title')}>
      <ol className="week__days">
        {days.map(day => (
          <li key={day.date}>
            <Link
              className="week__day"
              to={day.isToday ? '/play' : `/play?date=${day.date}`}
              data-state={day.puzzle}
              aria-current={day.isToday ? 'date' : undefined}
              aria-label={t('games.week.day', {
                date: format(day.date, {
                  weekday: 'long',
                  month: 'long',
                  day: 'numeric',
                }),
                state: t(`games.week.state.${day.puzzle}`),
              })}
            >
              <span className="week__name" aria-hidden="true">
                {format(day.date, {weekday: 'narrow'})}
              </span>
              <span className="week__dot" aria-hidden="true">
                {day.puzzle === 'won' ? (
                  <Icon name="check" size={16} />
                ) : day.puzzle === 'gaveUp' ? (
                  <Icon name="flag" size={14} />
                ) : (
                  day.day
                )}
              </span>
            </Link>
          </li>
        ))}
      </ol>
    </nav>
  );
}

function Hero({today, version}: {today: string; version: number}) {
  const {t} = useI18n();
  const format = useDateFormat();
  void version;
  const games = loadGames(storage());
  const records = loadRecords(storage());
  const stats = computeStats(games, today);
  const done = finishedToday(
    puzzleStatus(games, today),
    creditStatus(records, today),
  );
  return (
    <section className="games-hero" aria-labelledby="games-title">
      <div className="games-hero__top">
        <div className="games-hero__text">
          <p className="games-hero__overline">
            <Icon name="calendar" size={16} />
            {t('games.today')}
            <span aria-hidden="true">·</span>
            {format(today, {weekday: 'long', month: 'long', day: 'numeric'})}
          </p>
          <h1 id="games-title" className="games-hero__title">
            {t('games.title')}
          </h1>
          <p className="games-hero__lead">{t('games.lead')}</p>
        </div>
        <div className="games-hero__side">
          <dl className="games-hero__stats">
            <div
              className="games-hero__stat"
              data-hot={stats.currentStreak > 0 || undefined}
            >
              <dt>{t('games.streak.label')}</dt>
              <dd>
                <Icon name="fire" size={28} />
                <span>{t('games.streak', {count: stats.currentStreak})}</span>
              </dd>
            </div>
            <div className="games-hero__stat">
              <dt>{t('games.today')}</dt>
              <dd>
                <span className="games-hero__rings" aria-hidden="true">
                  {[0, 1].map(i => (
                    <span key={i} data-done={i < done || undefined} />
                  ))}
                </span>
                <span>{t('games.today.progress', {done})}</span>
              </dd>
            </div>
          </dl>
          <WeekStrip today={today} />
        </div>
      </div>
      <div className="today-grid stagger">
        <div style={{'--i': 0} as CSSProperties} className="today-grid__lead">
          <PuzzleTile today={today} />
        </div>
        <div style={{'--i': 1} as CSSProperties}>
          <CreditTile today={today} version={version} />
        </div>
        <div style={{'--i': 2} as CSSProperties}>
          <PathTile today={today} />
        </div>
      </div>
    </section>
  );
}

function StatsSection({today, version}: {today: string; version: number}) {
  const {t} = useI18n();
  void version;
  const puzzle = computeStats(loadGames(storage()), today);
  const credit = computeTriviaStats(loadRecords(storage()), today);
  const rows: [string, string][] = [
    [t('games.stats.puzzleSolved'), String(puzzle.won)],
    [t('play.stats.winRate'), `${puzzle.winRate}%`],
    [t('play.stats.maxStreak'), String(puzzle.maxStreak)],
    [t('games.stats.creditPlayed'), String(credit.played)],
    [
      t('games.stats.creditAverage'),
      credit.played ? String(credit.average) : '–',
    ],
    [t('games.stats.creditPerfect'), String(credit.perfect)],
  ];
  return (
    <section className="games-section" aria-labelledby="games-stats">
      <h2 id="games-stats" className="games-section__title">
        {t('games.stats')}
      </h2>
      <dl className="stats games-stats">
        {rows.map(([label, value]) => (
          <div key={label} className="stat">
            <dt className="stat__label">{label}</dt>
            <dd className="stat__value">{value}</dd>
          </div>
        ))}
      </dl>
      <p className="games-section__note">{t('games.stats.note')}</p>
    </section>
  );
}

function ArchiveSection({today}: {today: string}) {
  const {t} = useI18n();
  const [, setSearch] = useSearchParams();
  const yesterday = addDays(today, -1);
  return (
    <section
      className="games-section games-archive"
      aria-labelledby="games-archive"
    >
      <div>
        <h2 id="games-archive" className="games-section__title">
          {t('games.archive.title')}
        </h2>
        <p className="games-section__note">{t('games.archive.body')}</p>
      </div>
      <div className="games-archive__actions">
        <Link
          className="btn btn--tonal"
          to={yesterday >= LAUNCH_DAY ? `/play?date=${yesterday}` : '/play'}
        >
          <Icon name="puzzle" />
          {t('games.archive.puzzle')}
        </Link>
        <button
          type="button"
          className="btn btn--tonal"
          disabled={yesterday < LAUNCH_DAY}
          onClick={() => {
            setSearch({date: yesterday}, {replace: true});
            document
              .getElementById('credit-check')
              ?.scrollIntoView({block: 'start'});
          }}
        >
          <Icon name="quiz" />
          {t('games.archive.credit')}
        </button>
      </div>
    </section>
  );
}

function CreditSection({
  date,
  today,
  onProgress,
}: {
  date: string;
  today: string;
  onProgress: () => void;
}) {
  const {t} = useI18n();
  const [search, setSearch] = useSearchParams();
  function go(day: string | null) {
    const next = new URLSearchParams(search);
    if (day && day !== today) next.set('date', day);
    else next.delete('date');
    setSearch(next, {replace: true});
  }
  return (
    <section
      className="credit-section"
      id="credit-check"
      aria-labelledby="game-credit"
    >
      <div className="credit-section__head">
        <div>
          <p className="credit-section__eyebrow">
            <Icon name="quiz" size={16} />
            {t('games.credit.section')}
          </p>
          <h2 id="game-credit" className="credit-section__title" tabIndex={-1}>
            {t('games.credit.title', {number: dayNumber(date)})}
          </h2>
        </div>
        <nav className="credit-archive" aria-label={t('games.credit.archive')}>
          <button
            type="button"
            className="icon-btn"
            disabled={date <= LAUNCH_DAY}
            onClick={() => go(addDays(date, -1))}
          >
            <Icon name="chevronStart" label={t('games.credit.previous')} />
          </button>
          <label className="credit-archive__date">
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
            type="button"
            className="icon-btn"
            disabled={date >= today}
            onClick={() => go(addDays(date, 1))}
          >
            <Icon name="chevron" label={t('games.credit.nextDay')} />
          </button>
          {date !== today && (
            <button
              type="button"
              className="btn btn--tonal btn--compact"
              onClick={() => go(null)}
            >
              {t('games.credit.today')}
            </button>
          )}
        </nav>
      </div>
      <CreditCheck date={date} today={today} onProgress={onProgress} />
    </section>
  );
}

export default function GamesScreen() {
  const {t} = useI18n();
  const flags = useConfigFlags();
  const location = useLocation();
  const [search] = useSearchParams();
  const today = useToday();
  const puzzle = usePuzzle(today, flags.play !== false);
  // Bumped when Credit check progresses, so the hero re-reads the device's progress.
  const [version, setVersion] = useState(0);
  const onProgress = useCallback(() => setVersion(v => v + 1), []);
  usePageTitle(t('nav.games'));
  useAmbient(puzzle.data?.target.displayName ?? null);
  const requested = search.get('date');
  const date =
    requested && validPuzzleDate(requested, today) ? requested : today;

  // Links to a part of the hub (#credit-check, #leaderboards) land on it.
  useEffect(() => {
    if (!location.hash) return;
    const el = document.getElementById(location.hash.slice(1));
    el?.scrollIntoView({block: 'start'});
  }, [location.hash]);

  if (flags.play === false) {
    return (
      <div className="games">
        <section
          className="games-hero games-hero--off"
          aria-labelledby="games-title"
        >
          <span className="games-hero__off-icon" aria-hidden="true">
            <Icon name="puzzle" size={32} />
          </span>
          <h1 id="games-title" className="games-hero__title">
            {t('nav.games')}
          </h1>
          <p className="games-hero__lead">{t('games.off')}</p>
          <div className="games-archive__actions">
            <Link className="btn btn--filled" to="/stories">
              <Icon name="movie" />
              {t('nav.stories')}
            </Link>
            <Link className="btn btn--tonal" to="/explore">
              <Icon name="explore" />
              {t('nav.explore')}
            </Link>
          </div>
        </section>
      </div>
    );
  }
  return (
    <div className="games">
      <Hero today={today} version={version} />
      <CreditSection date={date} today={today} onProgress={onProgress} />
      <Leaderboards date={today} placement="hub" />
      <StatsSection today={today} version={version} />
      <ArchiveSection today={today} />
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
