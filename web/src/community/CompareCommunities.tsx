/**
 * Compare with another campus or city, side by side: the two communities as
 * columns, how many top artists they share, and each shared artist with its
 * rank on both charts.
 */
import {useState, type CSSProperties} from 'react';
import {Link} from 'react-router';

import {
  communityId,
  useCommunityChart,
  type Community,
  type CommunityChart,
} from '../api/community';
import {artistPath, imageOf} from '../components/ArtistRow';
import {Icon} from '../components/Icon';
import {Cover} from '../components/Shelf';
import {useI18n} from '../i18n/i18n';
import {Block} from '../social/Hero';

import {CommunityPicker, DemoBadge, plainName} from './CommunityPicker';
import {overlap, overlapShare} from './format';
import {CommunityMark} from './CommunityMark';

function Side({
  community,
  chart,
}: {
  community: Community;
  chart: CommunityChart | undefined;
}) {
  const {t} = useI18n();
  return (
    <div className="versus__side">
      <CommunityMark community={community} allowWide={false} />
      <span className="versus__name">
        <bdi>{plainName(community)}</bdi>
      </span>
      <span className="versus__meta">
        {chart?.state === 'LOCKED'
          ? t('around.compare.sideLocked')
          : chart
            ? t('around.compare.sideArtists', {count: chart.artists.length})
            : t('state.loading')}
      </span>
      {community.synthetic && <DemoBadge />}
    </div>
  );
}

function Versus({chart, other}: {chart: CommunityChart; other: Community}) {
  const {t, formatNumber} = useI18n();
  const theirs = useCommunityChart(communityId(other.name));
  const unlocked = theirs.data && theirs.data.state !== 'LOCKED';
  const shared = unlocked ? overlap(chart.artists, theirs.data.artists) : [];
  const share = unlocked
    ? overlapShare(shared.length, chart.artists, theirs.data.artists)
    : 0;
  const byName = new Map(chart.artists.map(r => [r.artist.name, r.artist]));
  const here = chart.community.shortName;
  const there = other.shortName;

  return (
    <div className="versus">
      <div className="versus__head">
        <Side community={chart.community} chart={chart} />
        <div className="versus__score">
          {theirs.isPending ? (
            <span className="skeleton versus__score-skel" />
          ) : unlocked ? (
            <>
              <span className="versus__percent">
                {formatNumber(share, {style: 'percent'})}
              </span>
              <span className="versus__score-label">
                {t('around.compare.overlap')}
              </span>
            </>
          ) : (
            <Icon name="lock" />
          )}
        </div>
        <Side community={other} chart={theirs.data} />
      </div>

      {theirs.isError && <p className="muted">{t('state.error.title')}</p>}
      {theirs.data?.state === 'LOCKED' && (
        <p className="quiet-note">
          <Icon name="lock" />
          <span>{t('around.compare.locked', {name: there})}</span>
        </p>
      )}
      {unlocked && (
        <>
          <p className="versus__summary">
            {t('around.compare.shared', {count: shared.length, name: there})}
          </p>
          {shared.length > 0 && (
            <ol className="versus__rows stagger">
              {shared.slice(0, 10).map((item, i) => {
                const artist = byName.get(item.name);
                if (!artist) return null;
                return (
                  <li key={item.name} style={{'--i': i} as CSSProperties}>
                    <Link className="versus__row" to={artistPath(artist)}>
                      <span
                        className="versus__rank"
                        aria-label={t('around.compare.rankAt', {
                          rank: item.rankA,
                          name: here,
                        })}
                      >
                        {item.rankA}
                      </span>
                      <span className="versus__artist">
                        <Cover
                          name={artist.displayName}
                          image={imageOf(artist)}
                          round
                        />
                        <bdi>{artist.displayName}</bdi>
                      </span>
                      <span
                        className="versus__rank"
                        aria-label={t('around.compare.rankAt', {
                          rank: item.rankB,
                          name: there,
                        })}
                      >
                        {item.rankB}
                      </span>
                    </Link>
                  </li>
                );
              })}
            </ol>
          )}
        </>
      )}
    </div>
  );
}

export function CompareCommunities({chart}: {chart: CommunityChart}) {
  const {t} = useI18n();
  const [other, setOther] = useState<Community | null>(null);
  const kind = chart.community.kind;
  return (
    <Block
      id="compare-title"
      eyebrow={t('around.compare.eyebrow')}
      title={t(`around.compare.${kind}`)}
      className="compare-communities"
      action={
        other && (
          <button
            type="button"
            className="btn btn--outlined btn--compact"
            onClick={() => setOther(null)}
          >
            {t('around.compare.clear')}
          </button>
        )
      }
    >
      {other ? (
        <Versus chart={chart} other={other} />
      ) : (
        <CommunityPicker
          kind={kind}
          exclude={chart.community.name}
          label={t(`around.compare.search.${kind}`)}
          onPick={setOther}
          compact
        />
      )}
    </Block>
  );
}
