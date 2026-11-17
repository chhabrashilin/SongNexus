/** A community chart: locked progress, or top artists, rising, the ranked list and genres. */
import {Link} from 'react-router';

import {idOf} from '../api/client';
import type {
  ChartArtist,
  CommunityChart,
  ListenerRange,
} from '../api/community';
import {useConfigFlags} from '../app/flags';
import {ArtistRow} from '../components/ArtistRow';
import {Icon} from '../components/Icon';
import {CoverCard, Shelf} from '../components/Shelf';
import {useSnackbar} from '../components/Snackbar';
import {useI18n} from '../i18n/i18n';

import {CompareCommunities} from './CompareCommunities';
import {rangeParts, shareUrl, unlockProgress} from './format';

/** How many artists ride the shelf; the full ranked list follows it. */
const SHELF = 10;

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

function Movement({row}: {row: ChartArtist}) {
  const {t} = useI18n();
  if (!row.movement) return null;
  const label = t(`around.move.${row.movement}`, {places: row.places});
  const glyph = {UP: '▲', DOWN: '▼', SAME: '–', NEW: '•'}[row.movement];
  return (
    <span className="movement" data-move={row.movement}>
      <span aria-hidden="true">{glyph}</span>
      <span className="movement__text">{label}</span>
    </span>
  );
}

function OpenWeb({row}: {row: ChartArtist}) {
  const {t} = useI18n();
  return (
    <Link
      className="icon-btn"
      to={`/explore/${idOf(row.artist.name)}`}
      aria-label={t('around.openWeb', {name: row.artist.displayName})}
      title={t('around.openWeb', {name: row.artist.displayName})}
    >
      <Icon name="explore" />
    </Link>
  );
}

function ChartRow({row}: {row: ChartArtist}) {
  const {t} = useI18n();
  const listeners = useListeners();
  return (
    <ArtistRow
      artist={row.artist}
      subtitle={
        <>
          <span className="chart-rank">
            {t('around.rank', {rank: row.rank})}
          </span>
          {' · '}
          {listeners(row.listeners)}
        </>
      }
      meta={<Movement row={row} />}
      action={<OpenWeb row={row} />}
    />
  );
}

function Locked({chart}: {chart: CommunityChart}) {
  const {t} = useI18n();
  const flags = useConfigFlags();
  const share = useShareCommunity();
  const name = chart.community.shortName;
  const have = chart.minListeners - chart.listenersNeeded;
  const progress = unlockProgress(chart.listenersNeeded, chart.minListeners);
  return (
    <section className="card unlock" aria-labelledby="unlock-title">
      <h2 id="unlock-title">
        {t('around.locked.title', {name, count: chart.listenersNeeded})}
      </h2>
      <div
        className="unlock__meter"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={chart.minListeners}
        aria-valuenow={have}
        aria-label={t('around.locked.progress', {
          have,
          min: chart.minListeners,
        })}
      >
        <span
          className="unlock__fill"
          style={{inlineSize: `${progress * 100}%`}}
        />
      </div>
      <p className="unlock__count">
        {t('around.locked.progress', {have, min: chart.minListeners})}
      </p>
      <p className="muted">
        {t('around.locked.body', {min: chart.minListeners, name})}
      </p>
      <div className="row">
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

export function ChartView({chart}: {chart: CommunityChart}) {
  const {t, locale} = useI18n();
  const listeners = useListeners();
  const name = chart.community.shortName;
  const updated = new Date(chart.updateTime).toLocaleTimeString(locale, {
    hour: 'numeric',
    minute: '2-digit',
  });

  return (
    <div className="chart stack">
      {chart.demoData && (
        <p className="banner chart__demo" role="note">
          <Icon name="info" />
          {t('around.demo')}
        </p>
      )}
      {chart.state === 'LOCKED' ? (
        <Locked chart={chart} />
      ) : (
        <>
          {chart.listeners && (
            <p className="muted">{listeners(chart.listeners, true)}</p>
          )}
          <Shelf
            title={t('around.top.title')}
            eyebrow={t('around.top.eyebrow', {name})}
          >
            {chart.artists.slice(0, SHELF).map(row => (
              <CoverCard
                key={row.artist.name}
                round
                to={`/artist/${idOf(row.artist.name)}`}
                title={row.artist.displayName}
                subtitle={t('around.cardSubtitle', {
                  rank: row.rank,
                  listeners: listeners(row.listeners),
                })}
              />
            ))}
          </Shelf>

          <section className="section" aria-labelledby="rising-title">
            <h2 id="rising-title">{t('around.rising.title')}</h2>
            <p className="muted">
              {chart.historyAvailable
                ? chart.rising.length > 0
                  ? t('around.rising.body')
                  : t('around.rising.empty')
                : t('around.rising.none')}
            </p>
            {chart.rising.length > 0 && (
              <ol className="list">
                {chart.rising.map(row => (
                  <ChartRow key={row.artist.name} row={row} />
                ))}
              </ol>
            )}
          </section>

          <section className="section" aria-labelledby="chart-title">
            <h2 id="chart-title">{t('around.chart.title')}</h2>
            <ol className="list chart__list">
              {chart.artists.map(row => (
                <ChartRow key={row.artist.name} row={row} />
              ))}
            </ol>
          </section>

          {chart.genres.length > 0 && (
            <section className="section" aria-labelledby="genres-title">
              <h2 id="genres-title">{t('around.genres.title')}</h2>
              <ul className="chips chart__genres">
                {chart.genres.map(genre => (
                  <li key={genre.genre} className="chip chip--static">
                    <bdi>{genre.displayName}</bdi>
                    <span className="chip__meta">
                      {listeners(genre.listeners)}
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          )}

          <CompareCommunities chart={chart} />
        </>
      )}
      <p className="muted chart__updated">
        {t('around.updated', {time: updated})}
      </p>
    </div>
  );
}
