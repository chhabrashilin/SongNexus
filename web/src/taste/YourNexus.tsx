/**
 * "Your Nexus": a taste profile as a set of cards. The genre mix and decade
 * spread are drawn with the data colors only, each with a text equivalent; the
 * rest are people (most central, hidden connectors, the tightest cluster, the
 * most surprising pair). Everything is computed from the credits graph; the
 * cards say so, and offer the summary as text and a link to share.
 */
import type {CSSProperties} from 'react';
import {Link} from 'react-router';

import {idOf} from '../api/client';
import type {TasteProfile} from '../api/personal';
import {artistPath, imageOf} from '../components/ArtistRow';
import {Icon} from '../components/Icon';
import {Cover} from '../components/Shelf';
import {useSnackbar} from '../components/Snackbar';
import {useI18n} from '../i18n/i18n';
import {PortraitStack} from '../social/Chain';

import {decadeBars, genreSlices, nexusUrl, peakDecade} from './taste';

function GenreMix({profile}: {profile: TasteProfile}) {
  const {t} = useI18n();
  const slices = genreSlices(profile.genres);
  return (
    <figure
      className="nexus-card nexus-card--wide"
      aria-labelledby="nexus-genres"
    >
      <figcaption className="nexus-card__head">
        <span className="nexus-card__overline">
          {t('taste.genres.overline')}
        </span>
        <span id="nexus-genres" className="nexus-card__title">
          {slices[0]?.label
            ? t('taste.genres.title', {genre: slices[0].label})
            : t('taste.genres.none')}
        </span>
      </figcaption>
      {slices.length > 0 && (
        <>
          <div className="mix" aria-hidden="true">
            {slices.map(slice => (
              <span
                key={slice.key}
                className="mix__part"
                style={
                  {
                    '--share': slice.percent,
                    background: slice.color,
                  } as CSSProperties
                }
              />
            ))}
          </div>
          <ul className="mix__legend">
            {slices.map(slice => (
              <li key={slice.key}>
                <span
                  className="mix__swatch"
                  style={{background: slice.color}}
                  aria-hidden="true"
                />
                <span className="mix__name">
                  <bdi>{slice.label ?? t('taste.genres.other')}</bdi>
                </span>
                <span className="mix__value">
                  {t('taste.percent', {percent: slice.percent})}
                </span>
              </li>
            ))}
          </ul>
        </>
      )}
      {profile.unknownGenreArtistCount > 0 && (
        <p className="nexus-card__foot">
          {t('taste.genres.unknown', {count: profile.unknownGenreArtistCount})}
        </p>
      )}
    </figure>
  );
}

function DecadeSpread({profile}: {profile: TasteProfile}) {
  const {t} = useI18n();
  const bars = decadeBars(profile.decades);
  const peak = peakDecade(profile.decades);
  return (
    <figure
      className="nexus-card nexus-card--wide"
      aria-labelledby="nexus-decades"
    >
      <figcaption className="nexus-card__head">
        <span className="nexus-card__overline">
          {t('taste.decades.overline')}
        </span>
        <span id="nexus-decades" className="nexus-card__title">
          {peak === null
            ? t('taste.decades.none')
            : t('taste.decades.title', {decade: String(peak)})}
        </span>
      </figcaption>
      {bars.length > 0 && (
        <>
          <ol className="decades" aria-hidden="true">
            {bars.map(bar => (
              <li
                key={bar.decade}
                className="decades__bar"
                data-peak={bar.peak || undefined}
                style={{'--h': bar.height} as CSSProperties}
              >
                <span className="decades__value">
                  {t('taste.percent', {percent: bar.percent})}
                </span>
                <span className="decades__fill" />
                <span className="decades__label">
                  {t('taste.decade.short', {
                    decade: String(bar.decade % 100).padStart(2, '0'),
                  })}
                </span>
              </li>
            ))}
          </ol>
          <table className="visually-hidden">
            <caption>{t('taste.decades.overline')}</caption>
            <tbody>
              {bars.map(bar => (
                <tr key={bar.decade}>
                  <th scope="row">
                    {t('taste.decade.long', {decade: String(bar.decade)})}
                  </th>
                  <td>{t('taste.percent', {percent: bar.percent})}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </figure>
  );
}

function Central({profile}: {profile: TasteProfile}) {
  const {t} = useI18n();
  const central = profile.mostCentral;
  if (!central) return null;
  return (
    <article
      className="nexus-card nexus-card--person"
      aria-labelledby="nexus-central"
    >
      <span className="nexus-card__overline">
        {t('taste.central.overline')}
      </span>
      <Link className="nexus-person" to={artistPath(central.artist)}>
        <Cover
          name={central.artist.displayName}
          image={imageOf(central.artist)}
          round
        />
        <span id="nexus-central" className="nexus-card__title">
          <bdi>{central.artist.displayName}</bdi>
        </span>
      </Link>
      <p className="nexus-card__body">
        {t('taste.central.body', {count: central.linkedCount})}
      </p>
      <Link
        className="btn btn--tonal btn--compact"
        to={`/explore/${idOf(central.artist.name)}`}
      >
        <Icon name="explore" />
        {t('taste.central.web')}
      </Link>
    </article>
  );
}

function Pair({profile}: {profile: TasteProfile}) {
  const {t} = useI18n();
  const pair = profile.surprisingPair;
  if (!pair) return null;
  const a = pair.artistA;
  const b = pair.artistB;
  return (
    <article
      className="nexus-card nexus-card--pair"
      aria-labelledby="nexus-pair"
    >
      <span className="nexus-card__overline">{t('taste.pair.overline')}</span>
      <div className="nexus-pair" aria-hidden="true">
        <Cover name={a.displayName} image={imageOf(a)} round />
        <span className="nexus-pair__steps">{pair.steps}</span>
        <Cover name={b.displayName} image={imageOf(b)} round />
      </div>
      <p id="nexus-pair" className="nexus-card__title">
        <bdi>{t('taste.pair.title', {a: a.displayName, b: b.displayName})}</bdi>
      </p>
      <p className="nexus-card__body">
        {t('taste.pair.body', {count: pair.steps})}
      </p>
      <Link
        className="btn btn--tonal btn--compact"
        to={`/six-degrees?from=${idOf(a.name)}&to=${idOf(b.name)}`}
      >
        <Icon name="route" />
        {t('taste.pair.path')}
      </Link>
    </article>
  );
}

function Cluster({profile}: {profile: TasteProfile}) {
  const {t} = useI18n();
  const cluster = profile.tightestCluster;
  if (!cluster || cluster.size < 2) return null;
  return (
    <article className="nexus-card" aria-labelledby="nexus-cluster">
      <span className="nexus-card__overline">
        {t('taste.cluster.overline')}
      </span>
      <PortraitStack artists={cluster.artists} max={6} />
      <p id="nexus-cluster" className="nexus-card__title">
        {t('taste.cluster.title', {count: cluster.size})}
      </p>
      <p className="nexus-card__body">
        <bdi>
          {t('taste.cluster.body', {
            min: cluster.minLinks,
            names: cluster.artists
              .slice(0, 4)
              .map(a => a.displayName)
              .join(', '),
          })}
        </bdi>
      </p>
    </article>
  );
}

function Connectors({profile}: {profile: TasteProfile}) {
  const {t} = useI18n();
  const connectors = profile.hiddenConnectors.slice(0, 4);
  if (connectors.length === 0) return null;
  return (
    <article
      className="nexus-card nexus-card--wide"
      aria-labelledby="nexus-connectors"
    >
      <span className="nexus-card__overline">
        {t('taste.connectors.overline')}
      </span>
      <p id="nexus-connectors" className="nexus-card__title">
        {t('taste.connectors.title')}
      </p>
      <ol className="nexus-connectors">
        {connectors.map(c => (
          <li key={c.artist.name}>
            <Link className="rank-row" to={artistPath(c.artist)}>
              <Cover
                name={c.artist.displayName}
                image={imageOf(c.artist)}
                round
              />
              <span className="rank-row__text">
                <span className="rank-row__title">
                  <bdi>{c.artist.displayName}</bdi>
                </span>
                <span className="rank-row__sub">
                  {t('taste.connectors.links', {count: c.linkedCount})}
                </span>
              </span>
            </Link>
          </li>
        ))}
      </ol>
    </article>
  );
}

/** The summary as text, for pasting anywhere. */
export function useNexusText(profile: TasteProfile) {
  const {t} = useI18n();
  const slices = genreSlices(profile.genres).filter(s => s.label);
  const peak = peakDecade(profile.decades);
  const parts = [
    slices.length > 0
      ? t('taste.share.genres', {
          genres: slices
            .slice(0, 3)
            .map(s =>
              t('taste.share.genre', {genre: s.label!, percent: s.percent}),
            )
            .join(', '),
        })
      : null,
    peak === null ? null : t('taste.share.decade', {decade: String(peak)}),
    profile.mostCentral
      ? t('taste.share.central', {name: profile.mostCentral.artist.displayName})
      : null,
    profile.surprisingPair
      ? t('taste.share.pair', {
          a: profile.surprisingPair.artistA.displayName,
          b: profile.surprisingPair.artistB.displayName,
          count: profile.surprisingPair.steps,
        })
      : null,
  ].filter(Boolean);
  return t('taste.share.text', {
    parts: parts.join(' · '),
    link: nexusUrl(globalThis.location?.origin ?? ''),
  });
}

function ShareActions({profile}: {profile: TasteProfile}) {
  const {t} = useI18n();
  const snackbar = useSnackbar();
  const text = useNexusText(profile);
  const url = nexusUrl(globalThis.location.origin);
  async function copy(value: string, done: string) {
    try {
      await navigator.clipboard.writeText(value);
      snackbar(done);
    } catch {
      snackbar(t('friends.invite.copyFailed'));
    }
  }
  async function share() {
    try {
      await navigator.share({title: t('taste.title'), text, url});
    } catch {
      // Dismissed: the copy buttons are still there.
    }
  }
  return (
    <div className="nexus__share">
      <button
        type="button"
        className="btn btn--filled"
        onClick={() => void copy(text, t('taste.share.copied'))}
      >
        <Icon name="copy" />
        {t('taste.share.copy')}
      </button>
      <button
        type="button"
        className="btn btn--tonal"
        onClick={() => void copy(url, t('action.linkCopied'))}
      >
        <Icon name="link" />
        {t('action.copyLink')}
      </button>
      {typeof navigator.share === 'function' && (
        <button
          type="button"
          className="btn btn--tonal"
          onClick={() => void share()}
        >
          <Icon name="share" />
          {t('action.share')}
        </button>
      )}
    </div>
  );
}

export function NexusSkeleton() {
  const {t} = useI18n();
  return (
    <div className="nexus-grid" role="status">
      <span className="visually-hidden">{t('state.loading')}</span>
      <span className="skeleton nexus-card nexus-card--wide nexus-skel" />
      <span className="skeleton nexus-card nexus-card--wide nexus-skel" />
      <span className="skeleton nexus-card nexus-skel" />
      <span className="skeleton nexus-card nexus-skel" />
    </div>
  );
}

/** The cards. `from` says what was profiled: your listening or one playlist. */
export function YourNexus({
  profile,
  from,
}: {
  profile: TasteProfile;
  from: 'listening' | 'playlist';
}) {
  const {t, formatNumber} = useI18n();
  if (profile.artistCount === 0)
    return (
      <div className="empty-card">
        <Icon name="spark" size={32} />
        <p className="empty-card__title">{t('taste.empty.title')}</p>
        <p className="muted">{t('taste.empty.body')}</p>
      </div>
    );
  return (
    <div className="nexus">
      <div className="nexus__summary">
        <dl className="stats">
          <div className="stat">
            <dt className="stat__label">{t('taste.stat.artists')}</dt>
            <dd className="stat__value">{formatNumber(profile.artistCount)}</dd>
          </div>
          <div className="stat">
            <dt className="stat__label">{t('taste.stat.collaborators')}</dt>
            <dd className="stat__value">
              {formatNumber(profile.collaboratorsReached)}
            </dd>
          </div>
          {profile.surprisingPair && (
            <div className="stat">
              <dt className="stat__label">{t('taste.stat.span')}</dt>
              <dd className="stat__value">
                {formatNumber(profile.surprisingPair.steps)}
              </dd>
            </div>
          )}
        </dl>
        <ShareActions profile={profile} />
      </div>
      <div className="nexus-grid stagger">
        <GenreMix profile={profile} />
        <DecadeSpread profile={profile} />
        <Central profile={profile} />
        <Pair profile={profile} />
        <Cluster profile={profile} />
        <Connectors profile={profile} />
      </div>
      <p className="nexus__note">
        {t(
          from === 'listening' ? 'taste.note.listening' : 'taste.note.playlist',
        )}{' '}
        {profile.skippedArtistCount > 0 &&
          t('taste.note.skipped', {count: profile.skippedArtistCount})}
      </p>
    </div>
  );
}
