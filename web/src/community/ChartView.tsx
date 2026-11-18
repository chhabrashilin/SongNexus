/**
 * A community chart. Locked: progress toward the listener floor as pips, with
 * share and invite. Unlocked: the top three as a podium, the rest as ranked
 * rows with movement, what's rising, genres as bars, and a comparison.
 */
import {useState, type CSSProperties} from 'react';
import {Link} from 'react-router';

import {
  communityId,
  type ChartArtist,
  type CommunityChart,
  type ListenerRange,
} from '../api/community';
import {useConfigFlags} from '../app/flags';
import {artistPath, imageOf} from '../components/ArtistRow';
import {Icon} from '../components/Icon';
import {Cover} from '../components/Shelf';
import {useSnackbar} from '../components/Snackbar';
import {useI18n} from '../i18n/i18n';
import {Block} from '../social/Hero';

import {CompareCommunities} from './CompareCommunities';
import {rangeParts, shareUrl, unlockProgress} from './format';
import {WeeklyMovers} from './WeeklyMovers';

/** Ranked rows shown under the podium before "Show all". */
const ROWS = 9;
/** Above this floor the pips become a continuous bar. */
const MAX_PIPS = 25;

export function listenUrl(name: string): string {
  return `https://music.youtube.com/search?q=${encodeURIComponent(name)}`;
}

export function useListeners() {
  const {t, formatNumber} = useI18n();
  return (range: ListenerRange, community = false) => {
    const parts = rangeParts(range);
    const min = formatNumber(parts.min);
    const max = formatNumber(parts.max);
    if (community)
      return parts.kind === 'atLeast'
        ? t('around.listeners.community.atLeast', {min})
        : t('around.listeners.community.between', {min, max});
    return parts.kind === 'atLeast'
      ? t('around.listeners.atLeast', {min})
      : t('around.listeners.between', {min, max});
  };
}

/** Shares the Around you link for a community (system share sheet, or copies it). */
export function useShareCommunity() {
  const {t} = useI18n();
  const snackbar = useSnackbar();
  return async (name: string, displayName: string) => {
    const url = shareUrl(globalThis.location.origin, name);
    const text = t('around.share.text', {name: displayName});
    try {
      if (typeof navigator.share === 'function') {
        await navigator.share({title: displayName, text, url});
        return;
      }
      await navigator.clipboard.writeText(url);
      snackbar(t('action.linkCopied'));
    } catch {
      // The listener closed the share sheet, or the clipboard is unavailable.
    }
  };
}

/** Movement since last week: an arrow and words, never color alone. */
export function Movement({row}: {row: ChartArtist}) {
  const {t} = useI18n();
  if (!row.movement) return null;
  const label = t(`around.move.${row.movement}`, {places: row.places});
  if (row.movement === 'NEW')
    return (
      <span className="movement" data-move="NEW">
        {label}
      </span>
    );
  return (
    <span className="movement" data-move={row.movement} title={label}>
      {row.movement === 'SAME' ? (
        <Icon name="remove" size={16} />
      ) : (
        <Icon
          name={row.movement === 'UP' ? 'arrowUp' : 'arrowDown'}
          size={16}
        />
      )}
      <span className="movement__places" aria-hidden="true">
        {row.movement === 'SAME' ? '' : row.places}
      </span>
      <span className="visually-hidden">{label}</span>
    </span>
  );
}

export function RankRow({row, index}: {row: ChartArtist; index: number}) {
  const listeners = useListeners();
  return (
    <li style={{'--i': index} as CSSProperties}>
      <Link className="rank-row" to={artistPath(row.artist)}>
        <span className="rank-row__n">{row.rank}</span>
        <Cover
          name={row.artist.displayName}
          image={imageOf(row.artist)}
          round
        />
        <span className="rank-row__text">
          <span className="rank-row__title">
            <bdi>{row.artist.displayName}</bdi>
          </span>
          <span className="rank-row__sub">{listeners(row.listeners)}</span>
        </span>
        <Movement row={row} />
      </Link>
    </li>
  );
}

/** Progress toward the listener floor: one pip per listener needed. */
function UnlockMeter({have, min}: {have: number; min: number}) {
  const {t} = useI18n();
  const label = t('around.locked.progress', {have, min});
  if (min > MAX_PIPS)
    return (
      <div
        className="unlock__bar"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={min}
        aria-valuenow={have}
        aria-label={label}
      >
        <span
          className="unlock__bar-fill"
          style={{inlineSize: `${unlockProgress(min - have, min) * 100}%`}}
        />
      </div>
    );
  return (
    <div
      className="unlock__pips"
      role="progressbar"
      aria-valuemin={0}
      aria-valuemax={min}
      aria-valuenow={have}
      aria-label={label}
    >
      {Array.from({length: min}, (_, i) => (
        <span
          key={i}
          className="unlock__pip"
          data-on={i < have || undefined}
          style={{'--i': i} as CSSProperties}
        />
      ))}
    </div>
  );
}

function Locked({chart}: {chart: CommunityChart}) {
  const {t, formatNumber} = useI18n();
  const flags = useConfigFlags();
  const share = useShareCommunity();
  const name = chart.community.shortName;
  const have = Math.max(0, chart.minListeners - chart.listenersNeeded);
  return (
    <section className="unlock" aria-labelledby="unlock-title">
      <div className="unlock__head">
        <span className="unlock__lock">
          <Icon name="lock" />
        </span>
        <div className="unlock__numbers">
          <p className="unlock__big">
            <span className="unlock__have">{formatNumber(have)}</span>
            <span className="unlock__of">
              {t('around.locked.of', {min: formatNumber(chart.minListeners)})}
            </span>
          </p>
          <h2 id="unlock-title" className="unlock__title">
            {t('around.locked.title', {name, count: chart.listenersNeeded})}
          </h2>
        </div>
      </div>
      <UnlockMeter have={have} min={chart.minListeners} />
      <p className="unlock__body">
        {t('around.locked.body', {min: chart.minListeners, name})}
      </p>
      <div className="unlock__actions">
        <button
          type="button"
          className="btn btn--filled"
          onClick={() => void share(chart.community.name, name)}
        >
          <Icon name="share" />
          {t('around.share')}
        </button>
        {flags.friends !== false && (
          <Link className="btn btn--tonal" to="/friends">
            <Icon name="people" />
            {t('around.invite')}
          </Link>
        )}
      </div>
    </section>
  );
}

/** The top three, the leader in the middle and largest. */
function Podium({rows}: {rows: ChartArtist[]}) {
  const {t} = useI18n();
  const listeners = useListeners();
  return (
    <ol className="podium stagger" aria-label={t('around.top.title')}>
      {rows.slice(0, 3).map((row, i) => (
        <li
          key={row.artist.name}
          className="podium__place"
          data-rank={row.rank}
          style={{'--i': i} as CSSProperties}
        >
          <Link className="podium__link" to={artistPath(row.artist)}>
            <span className="podium__art">
              <Cover
                name={row.artist.displayName}
                image={imageOf(row.artist)}
                round
                eager
              />
              <span className="podium__rank" aria-hidden="true">
                {row.rank}
              </span>
            </span>
            <span className="podium__name">
              <span className="visually-hidden">
                {t('around.rank', {rank: row.rank})}{' '}
              </span>
              <bdi>{row.artist.displayName}</bdi>
            </span>
            <span className="podium__sub">{listeners(row.listeners)}</span>
          </Link>
          {i === 0 && (
            <a
              className="btn btn--tonal btn--compact listen"
              href={listenUrl(row.artist.displayName)}
              target="_blank"
              rel="noopener noreferrer"
            >
              <span className="listen__disc">
                <Icon name="play" />
              </span>
              {t('around.listen')}
            </a>
          )}
        </li>
      ))}
    </ol>
  );
}

function Genres({chart}: {chart: CommunityChart}) {
  const {t} = useI18n();
  const listeners = useListeners();
  const top = Math.max(1, ...chart.genres.map(g => g.listeners.min));
  const flat = new Set(chart.genres.map(g => g.listeners.min)).size === 1;
  if (flat)
    return (
      <Block id="genres-title" title={t('around.genres.title')}>
        <p className="muted">
          {t('around.genres.flat', {
            range: listeners(chart.genres[0]!.listeners),
          })}
        </p>
        <ul className="chips genre-chips">
          {chart.genres.slice(0, 12).map(genre => (
            <li key={genre.genre} className="chip genre-chip">
              <bdi>{genre.displayName}</bdi>
            </li>
          ))}
        </ul>
      </Block>
    );
  return (
    <Block id="genres-title" title={t('around.genres.title')}>
      <ul className="genre-bars">
        {chart.genres.slice(0, 8).map(genre => (
          <li key={genre.genre} className="genre-bar">
            <span className="genre-bar__name">
              <bdi>{genre.displayName}</bdi>
            </span>
            <span className="genre-bar__track" aria-hidden="true">
              <span
                className="genre-bar__fill"
                style={{inlineSize: `${(genre.listeners.min / top) * 100}%`}}
              />
            </span>
            <span className="genre-bar__value">
              {listeners(genre.listeners)}
            </span>
          </li>
        ))}
      </ul>
    </Block>
  );
}

export function ChartView({chart}: {chart: CommunityChart}) {
  const {t, locale, formatNumber} = useI18n();
  const range = (value: ListenerRange) => {
    const parts = rangeParts(value);
    return parts.kind === 'atLeast'
      ? t('around.range.atLeast', {min: formatNumber(parts.min)})
      : t('around.range.between', {
          min: formatNumber(parts.min),
          max: formatNumber(parts.max),
        });
  };
  const [all, setAll] = useState(false);
  const name = chart.community.shortName;
  const updated = new Date(chart.updateTime).toLocaleTimeString(locale, {
    hour: 'numeric',
    minute: '2-digit',
  });
  const rest = chart.artists.slice(3);
  const visible = all ? rest : rest.slice(0, ROWS);

  return (
    <div className="chart">
      {chart.demoData && (
        <p className="demo-note" role="note">
          <Icon name="info" />
          <span>{t('around.demo')}</span>
        </p>
      )}
      {chart.state === 'LOCKED' ? (
        <Locked chart={chart} />
      ) : (
        <>
          <dl className="stats chart__stats">
            {chart.listeners && (
              <div className="stat">
                <dt className="stat__label">{t('around.stat.listeners')}</dt>
                <dd className="stat__value">{range(chart.listeners)}</dd>
              </div>
            )}
            <div className="stat">
              <dt className="stat__label">{t('around.stat.artists')}</dt>
              <dd className="stat__value">
                {formatNumber(chart.artists.length)}
              </dd>
            </div>
            <div className="stat">
              <dt className="stat__label">{t('around.stat.updated')}</dt>
              <dd className="stat__value stat__value--time">{updated}</dd>
            </div>
          </dl>

          {chart.artists.length === 0 ? (
            <p className="muted">{t('around.chart.empty')}</p>
          ) : (
            <Block
              id="chart-title"
              eyebrow={t('around.top.eyebrow', {name})}
              title={t('around.chart.title')}
            >
              <Podium rows={chart.artists} />
              {rest.length > 0 && (
                <ol className="rank-grid stagger chart__rows">
                  {visible.map((row, i) => (
                    <RankRow key={row.artist.name} row={row} index={i} />
                  ))}
                </ol>
              )}
              {rest.length > ROWS && (
                <button
                  type="button"
                  className="btn btn--outlined chart__all"
                  aria-expanded={all}
                  onClick={() => setAll(value => !value)}
                >
                  {all
                    ? t('around.chart.fewer')
                    : t('around.chart.all', {count: chart.artists.length})}
                </button>
              )}
            </Block>
          )}

          <Block
            id="rising-title"
            eyebrow={t('around.rising.eyebrow')}
            title={t('around.rising.title')}
          >
            {chart.rising.length > 0 ? (
              <>
                <p className="muted">{t('around.rising.body')}</p>
                <ol className="rank-grid stagger">
                  {chart.rising.slice(0, 6).map((row, i) => (
                    <RankRow key={row.artist.name} row={row} index={i} />
                  ))}
                </ol>
              </>
            ) : (
              <p className="quiet-note">
                <Icon name="trendingUp" />
                <span>
                  {chart.historyAvailable
                    ? t('around.rising.empty')
                    : t('around.rising.none')}
                </span>
              </p>
            )}
          </Block>

          <WeeklyMovers id={communityId(chart.community.name)} />

          {chart.genres.length > 0 && <Genres chart={chart} />}

          <CompareCommunities chart={chart} />
        </>
      )}
      <p className="chart__updated">{t('around.updated', {time: updated})}</p>
    </div>
  );
}
