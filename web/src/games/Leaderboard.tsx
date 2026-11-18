/**
 * Leaderboards: campuses (aggregate only, with a player floor) and you and your
 * friends, for the daily puzzle and Credit check, today or this week. Putting
 * a score on them is opt-in and explicit: playing never needs an account, and
 * the server checks the play and keeps only the points.
 */
import {useId, useState, type ReactNode} from 'react';
import {Link} from 'react-router';

import {ApiError} from '../api/client';
import {
  useCampusLeaderboard,
  useFriendLeaderboard,
  useGameScores,
  useSubmitScore,
  type CampusLeaderboard,
  type Game,
  type LeaderboardPeriod,
  type ScoreSubmission,
} from '../api/discover';
import {useConfigFlags} from '../app/flags';
import {useAuth} from '../auth/AuthProvider';
import {Avatar} from '../components/ArtistRow';
import {Icon} from '../components/Icon';
import {Cover} from '../components/Shelf';
import {ErrorState} from '../components/States';
import {useI18n} from '../i18n/i18n';

import {playersRange, scoreable, scoreFor, visibleRows} from './scores';

const TOP = 5;

function useLeaderboardsOn(): boolean {
  const flags = useConfigFlags();
  return flags.leaderboards !== false && flags.play !== false;
}

/** A pill-shaped choice between a few values (radio semantics via aria-pressed chips). */
function Choice<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: T;
  options: {value: T; label: string}[];
  onChange: (value: T) => void;
}) {
  return (
    <div className="lb-choice" role="group" aria-label={label}>
      {options.map(option => (
        <button
          key={option.value}
          type="button"
          className="chip"
          aria-pressed={option.value === value}
          onClick={() => onChange(option.value)}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

function BoardSkeleton() {
  const {t} = useI18n();
  return (
    <div role="status" className="lb-list">
      <span className="visually-hidden">{t('state.loading')}</span>
      {Array.from({length: 4}, (_, i) => (
        <span key={i} className="lb-row lb-row--skeleton" aria-hidden="true">
          <span className="skeleton lb-skel lb-skel--n" />
          <span className="skeleton lb-skel lb-skel--avatar" />
          <span className="skeleton lb-skel lb-skel--text" />
        </span>
      ))}
    </div>
  );
}

function Panel({
  title,
  icon,
  badge,
  headingLevel,
  children,
}: {
  title: string;
  icon: 'school' | 'people';
  badge?: ReactNode;
  headingLevel: 2 | 3;
  children: ReactNode;
}) {
  const id = useId();
  const Heading = headingLevel === 2 ? 'h3' : 'h4';
  return (
    <section className="lb-panel" aria-labelledby={id}>
      <div className="lb-panel__head">
        <span className="lb-panel__icon" aria-hidden="true">
          <Icon name={icon} size={20} />
        </span>
        <Heading id={id} className="lb-panel__title">
          {title}
        </Heading>
        {badge}
      </div>
      {children}
    </section>
  );
}

function DemoBadge() {
  const {t} = useI18n();
  return (
    <span className="lb-demo" title={t('lb.demo.note')}>
      {t('lb.demo')}
    </span>
  );
}

function ViewerCampusLine({board}: {board: CampusLeaderboard}) {
  const {t} = useI18n();
  const auth = useAuth();
  if (auth.status !== 'signedIn') {
    return <p className="lb-viewer">{t('lb.campus.signedOut')}</p>;
  }
  const viewer = board.viewerCampus;
  if (!viewer || viewer.state === 'NO_CAMPUS' || !viewer.community) {
    return (
      <p className="lb-viewer">
        {t('lb.campus.none')}{' '}
        <Link to="/around-you">{t('lb.campus.choose')}</Link>
      </p>
    );
  }
  const name = viewer.community.displayName;
  return (
    <p className="lb-viewer" data-state={viewer.state}>
      <Icon name="school" size={18} />
      <bdi>
        {viewer.state === 'RANKED' && viewer.rank !== null
          ? t('lb.campus.ranked', {name, rank: viewer.rank})
          : t('lb.campus.needs', {name, count: viewer.playersNeeded})}
      </bdi>
    </p>
  );
}

function CampusBoard({
  game,
  period,
  date,
  headingLevel,
}: {
  game: Game;
  period: LeaderboardPeriod;
  date: string;
  headingLevel: 2 | 3;
}) {
  const {t} = useI18n();
  const board = useCampusLeaderboard(game, period, date);
  const [all, setAll] = useState(false);
  const data = board.data;
  const mineName = data?.viewerCampus?.community?.name ?? null;
  const rows = data?.campuses ?? [];
  const {top, mine} = visibleRows(
    rows,
    all ? rows.length : TOP,
    row => row.community.name === mineName,
  );
  return (
    <Panel
      title={t('lb.campus.title')}
      icon="school"
      headingLevel={headingLevel}
      badge={data?.demoData ? <DemoBadge /> : undefined}
    >
      {board.isPending ? (
        <BoardSkeleton />
      ) : board.isError ? (
        <ErrorState error={board.error} onRetry={() => void board.refetch()} />
      ) : (
        <>
          <ViewerCampusLine board={board.data} />
          {rows.length === 0 ? (
            <p className="lb-empty">{t('lb.campus.empty')}</p>
          ) : (
            <ol className="lb-list">
              {[...top, ...(mine ? [mine] : [])].map(row => {
                const players = playersRange(row.players);
                const isMine = row.community.name === mineName;
                return (
                  <li
                    key={row.community.name}
                    className="lb-row"
                    data-mine={isMine || undefined}
                    data-gap={(row === mine && top.length > 0) || undefined}
                  >
                    <span className="lb-row__n">
                      {t('lb.rank', {rank: row.rank})}
                    </span>
                    <Cover
                      name={
                        row.community.shortName || row.community.displayName
                      }
                    />
                    <span className="lb-row__text">
                      <span className="lb-row__title">
                        <bdi>{row.community.displayName}</bdi>
                      </span>
                      <span className="lb-row__sub">
                        {t(players.id, players.values)}
                        {isMine && (
                          <>
                            <span aria-hidden="true"> · </span>
                            {t('lb.campus.yours')}
                          </>
                        )}
                      </span>
                    </span>
                    <span className="lb-row__points">
                      <span aria-hidden="true">
                        {t('lb.campus.points', {points: row.averagePoints})}
                      </span>
                      <span className="visually-hidden">
                        {t('lb.campus.pointsLong', {points: row.averagePoints})}
                      </span>
                    </span>
                  </li>
                );
              })}
            </ol>
          )}
          {rows.length > TOP && (
            <button
              type="button"
              className="btn btn--text btn--compact lb-more"
              aria-expanded={all}
              onClick={() => setAll(a => !a)}
            >
              {all ? t('lb.showLess') : t('lb.showAll', {count: rows.length})}
            </button>
          )}
          <p className="lb-note">
            {t('lb.campus.note', {min: data?.minPlayers ?? 0})}
            {data?.demoData && <> {t('lb.demo.note')}</>}
          </p>
        </>
      )}
    </Panel>
  );
}

function FriendsBoard({
  game,
  period,
  date,
  headingLevel,
}: {
  game: Game;
  period: LeaderboardPeriod;
  date: string;
  headingLevel: 2 | 3;
}) {
  const {t} = useI18n();
  const auth = useAuth();
  const signedIn = auth.status === 'signedIn';
  const board = useFriendLeaderboard(game, period, date, signedIn);
  const [all, setAll] = useState(false);
  const rows = board.data?.standings ?? [];
  const {top, mine} = visibleRows(
    rows,
    all ? rows.length : TOP,
    row => row.isViewer,
  );
  return (
    <Panel
      title={t('lb.friends.title')}
      icon="people"
      headingLevel={headingLevel}
    >
      {!signedIn ? (
        <div className="lb-empty">
          <p>{t('lb.friends.signedOut')}</p>
          <button
            type="button"
            className="btn btn--tonal"
            disabled={auth.status === 'loading' || auth.status === 'signingIn'}
            onClick={() => void auth.signIn()}
          >
            <Icon name="person" />
            {t('shell.signIn')}
          </button>
        </div>
      ) : board.isPending ? (
        <BoardSkeleton />
      ) : board.isError ? (
        <ErrorState error={board.error} onRetry={() => void board.refetch()} />
      ) : rows.length === 0 ? (
        <div className="lb-empty">
          <p>{t('lb.friends.empty')}</p>
          <Link className="btn btn--tonal" to="/friends">
            <Icon name="add" />
            {t('lb.friends.invite')}
          </Link>
        </div>
      ) : (
        <>
          <ol className="lb-list">
            {[...top, ...(mine ? [mine] : [])].map(row => (
              <li
                key={row.person.user}
                className="lb-row"
                data-mine={row.isViewer || undefined}
                data-gap={(row === mine && top.length > 0) || undefined}
              >
                <span className="lb-row__n">
                  {t('lb.rank', {rank: row.rank})}
                </span>
                <Avatar name={row.person.displayName} />
                <span className="lb-row__text">
                  <span className="lb-row__title">
                    <bdi>{row.person.displayName}</bdi>
                    {row.isViewer && (
                      <span className="lb-you">{t('lb.you')}</span>
                    )}
                  </span>
                  <span className="lb-row__sub">
                    {t('lb.days', {count: row.daysPlayed})}
                  </span>
                </span>
                <span className="lb-row__points">
                  {t('lb.points', {points: row.points})}
                </span>
              </li>
            ))}
          </ol>
          {rows.length > TOP && (
            <button
              type="button"
              className="btn btn--text btn--compact lb-more"
              aria-expanded={all}
              onClick={() => setAll(a => !a)}
            >
              {all ? t('lb.showLess') : t('lb.showAll', {count: rows.length})}
            </button>
          )}
        </>
      )}
    </Panel>
  );
}

/**
 * The campus and friends boards. On the hub the listener picks the game; under
 * a finished game it is that game, and the period defaults to today.
 */
export function Leaderboards({
  game: fixedGame,
  date,
  placement,
}: {
  /** Fixed under a result; chosen by the listener on the hub. */
  game?: Game;
  date: string;
  placement: 'hub' | 'result';
}) {
  const {t} = useI18n();
  const on = useLeaderboardsOn();
  const titleId = useId();
  const [chosenGame, setGame] = useState<Game>('PUZZLE');
  const [period, setPeriod] = useState<LeaderboardPeriod>(
    placement === 'hub' ? 'WEEK' : 'DAY',
  );
  if (!on) return null;
  const game = fixedGame ?? chosenGame;
  const hub = placement === 'hub';
  const Heading = hub ? 'h2' : 'h3';
  return (
    <section
      className="lb"
      data-placement={placement}
      aria-labelledby={titleId}
      id={hub ? 'leaderboards' : undefined}
    >
      <div className="lb__head">
        <div className="lb__titles">
          {hub && <p className="lb__eyebrow">{t('lb.eyebrow')}</p>}
          <Heading id={titleId} className="lb__title">
            {t('lb.title')}
          </Heading>
        </div>
        <div className="lb__controls">
          {!fixedGame && (
            <Choice
              label={t('lb.game')}
              value={chosenGame}
              onChange={setGame}
              options={(['PUZZLE', 'TRIVIA'] as const).map(value => ({
                value,
                label: t(`lb.game.${value}`),
              }))}
            />
          )}
          <Choice
            label={t('lb.period')}
            value={period}
            onChange={setPeriod}
            options={(['DAY', 'WEEK'] as const).map(value => ({
              value,
              label: t(`lb.period.${value}`),
            }))}
          />
        </div>
      </div>
      <div className="lb__panels">
        <CampusBoard
          game={game}
          period={period}
          date={date}
          headingLevel={hub ? 2 : 3}
        />
        <FriendsBoard
          game={game}
          period={period}
          date={date}
          headingLevel={hub ? 2 : 3}
        />
      </div>
    </section>
  );
}

/**
 * Opt-in score submission under a finished game. Signed out, it says what
 * signing in adds; archive days are never scored; a score already on the
 * boards (from this or another device) shows as added.
 */
export function ScoreSubmit({
  game,
  date,
  today,
  play,
}: {
  game: Game;
  date: string;
  today: string;
  /** What to submit, or null when this play cannot be scored (a give-up). */
  play: ScoreSubmission | null;
}) {
  const {t} = useI18n();
  const on = useLeaderboardsOn();
  const auth = useAuth();
  const signedIn = auth.status === 'signedIn';
  const scores = useGameScores(signedIn && on);
  const submit = useSubmitScore();
  if (!on) return null;

  const existing = scoreFor(scores.data?.gameScores, game, date) ?? submit.data;
  const problem =
    submit.error instanceof ApiError
      ? submit.error.reason
      : submit.error
        ? 'x'
        : null;

  let body: ReactNode;
  if (!scoreable(date, today) || problem === 'SCORE_WINDOW_CLOSED') {
    body = <p className="score__text">{t('score.archive')}</p>;
  } else if (!play) {
    body = <p className="score__text">{t('score.gaveUp')}</p>;
  } else if (!signedIn) {
    body = (
      <>
        <p className="score__text">{t('score.signedOut')}</p>
        <button
          type="button"
          className="btn btn--tonal"
          disabled={auth.status === 'loading' || auth.status === 'signingIn'}
          onClick={() => void auth.signIn()}
        >
          <Icon name="person" />
          {t('shell.signIn')}
        </button>
      </>
    );
  } else if (existing) {
    body = (
      <p className="score__done">
        <Icon name="check" size={20} />
        {t('score.added', {points: existing.points})}
      </p>
    );
  } else if (scores.isPending || problem === 'SCORE_ALREADY_SUBMITTED') {
    body = (
      <span className="skeleton score__skel" role="status">
        <span className="visually-hidden">{t('state.loading')}</span>
      </span>
    );
  } else {
    body = (
      <>
        <p className="score__text">
          {t('score.body')} {t(`score.rules.${game}`)}
        </p>
        {problem && (
          <p className="score__error" role="alert">
            {t('score.failed')}
          </p>
        )}
        <button
          type="button"
          className="btn btn--filled"
          disabled={submit.isPending}
          onClick={() => submit.mutate(play)}
        >
          <Icon name="leaderboard" />
          {submit.isPending ? t('score.submitting') : t('score.submit')}
        </button>
      </>
    );
  }

  return (
    <div className="score" data-state={existing ? 'added' : undefined}>
      <p className="score__title">
        <Icon name="trophy" size={18} />
        {t('score.title')}
      </p>
      <div className="score__body" aria-live="polite">
        {body}
      </div>
    </div>
  );
}
