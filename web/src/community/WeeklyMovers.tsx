/**
 * Weekly movers: what climbed, dropped, entered and left a community chart
 * since a week ago, one group at a time. Movement is an arrow and words,
 * never color alone.
 */
import {useState, type CSSProperties} from 'react';
import {Link} from 'react-router';

import {
  useWeeklyMovers,
  type ChartMover,
  type WeeklyMovers as Movers,
} from '../api/community';
import {artistPath, imageOf} from '../components/ArtistRow';
import {Icon, type IconName} from '../components/Icon';
import {Cover} from '../components/Shelf';
import {useI18n} from '../i18n/i18n';
import {Block} from '../social/Hero';

import {DemoBadge} from './CommunityPicker';

export type MoverGroup = 'rose' | 'fell' | 'entered' | 'left';
const GROUPS: MoverGroup[] = ['rose', 'fell', 'entered', 'left'];
const ICON: Record<MoverGroup, IconName> = {
  rose: 'arrowUp',
  fell: 'arrowDown',
  entered: 'add',
  left: 'remove',
};
/** Rows shown per group. */
const ROWS = 6;

/** The first group with anyone in it, so the block never opens on an empty list. */
export function firstGroup(movers: Pick<Movers, MoverGroup>): MoverGroup {
  return GROUPS.find(group => movers[group].length > 0) ?? 'rose';
}

function MoverRow({
  mover,
  group,
  index,
}: {
  mover: ChartMover;
  group: MoverGroup;
  index: number;
}) {
  const {t} = useI18n();
  const rank = mover.rank ?? mover.previousRank ?? 0;
  const detail =
    group === 'rose' || group === 'fell'
      ? t(`around.movers.detail.${group}`, {
          places: mover.places,
          from: mover.previousRank ?? 0,
          to: mover.rank ?? 0,
        })
      : group === 'entered'
        ? t('around.movers.detail.entered', {rank})
        : t('around.movers.detail.left', {rank});
  return (
    <li style={{'--i': index} as CSSProperties}>
      <Link className="rank-row" to={artistPath(mover.artist)}>
        <span className="rank-row__n">{rank}</span>
        <Cover
          name={mover.artist.displayName}
          image={imageOf(mover.artist)}
          round
        />
        <span className="rank-row__text">
          <span className="rank-row__title">
            <bdi>{mover.artist.displayName}</bdi>
          </span>
          <span className="rank-row__sub">{detail}</span>
        </span>
        <span className="movement" data-move={group}>
          <Icon name={ICON[group]} size={16} />
          {(group === 'rose' || group === 'fell') && (
            <span aria-hidden="true">{mover.places}</span>
          )}
        </span>
      </Link>
    </li>
  );
}

export function WeeklyMovers({id}: {id: string}) {
  const {t} = useI18n();
  const movers = useWeeklyMovers(id);
  const [picked, setPicked] = useState<MoverGroup | null>(null);

  if (movers.isPending)
    return (
      <div className="movers-skeleton" role="status">
        <span className="visually-hidden">{t('state.loading')}</span>
        <span className="skeleton movers-skeleton__tabs" />
        <span className="skeleton movers-skeleton__rows" />
      </div>
    );
  // Movers are extra: when they fail, the chart above still stands.
  if (movers.isError || movers.data.state === 'LOCKED') return null;
  const data = movers.data;
  const group = picked ?? firstGroup(data);
  const rows = data[group];

  return (
    <Block
      id="movers-title"
      eyebrow={t('around.movers.eyebrow')}
      title={t('around.movers.title')}
      action={data.demoData ? <DemoBadge /> : undefined}
    >
      {data.state === 'NO_HISTORY' ? (
        <p className="quiet-note">
          <Icon name="calendar" />
          <span>{t('around.movers.noHistory')}</span>
        </p>
      ) : (
        <>
          <div
            className="segmented movers__tabs"
            role="tablist"
            aria-label={t('around.movers.title')}
          >
            {GROUPS.map(option => (
              <button
                key={option}
                type="button"
                role="tab"
                id={`movers-tab-${option}`}
                aria-controls="movers-panel"
                className="segmented__option"
                aria-selected={option === group}
                onClick={() => setPicked(option)}
              >
                <Icon name={ICON[option]} />
                {t(`around.movers.${option}`, {count: data[option].length})}
              </button>
            ))}
          </div>
          <div
            role="tabpanel"
            id="movers-panel"
            aria-labelledby={`movers-tab-${group}`}
          >
            {rows.length === 0 ? (
              <p className="quiet-note">
                <Icon name="info" />
                <span>{t(`around.movers.none.${group}`)}</span>
              </p>
            ) : (
              <ol className="rank-grid stagger" key={group}>
                {rows.slice(0, ROWS).map((mover, i) => (
                  <MoverRow
                    key={mover.artist.name}
                    mover={mover}
                    group={group}
                    index={i}
                  />
                ))}
              </ol>
            )}
          </div>
        </>
      )}
    </Block>
  );
}
