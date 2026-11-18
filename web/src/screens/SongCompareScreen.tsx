/**
 * Compare songs (R2-4, S1), head to head: two covers facing each other with
 * how alike they sound in the middle, the explained parts of that number, the
 * structure side by side, and the people who worked on both (and on only one).
 */
import type {CSSProperties} from 'react';
import {Link, useSearchParams} from 'react-router';

import {idOf, type ArtistSummary, type Schemas} from '../api/client';
import {useRecordingComparison} from '../api/queries';
import {useAmbient} from '../app/ambient';
import {usePageTitle} from '../app/Shell';
import {artistPath, imageOf} from '../components/ArtistRow';
import {useListFormat} from '../components/AskAnswer';
import {Icon} from '../components/Icon';
import {Cover} from '../components/Shelf';
import {EmptyState, ErrorState} from '../components/States';
import {MAGNITUDE_COLOR, SIDE_COLOR} from '../connect/mixtape';
import {
  ListenLink,
  Moment,
  PortraitChain,
  SongSlot,
  ToolHero,
} from '../connect/parts';
import {useI18n} from '../i18n/i18n';
import type {MessageId} from '../i18n/messages';
import {MOODS, Meter, percent, useDescribe} from '../songs/Descriptors';
import {ShareButton} from '../social/ShareSheet';

const KNOWN_ROLES = new Set([
  'primary',
  'featured',
  'producer',
  'vocal',
  'instrument',
  'performer',
  'programming',
  'arranger',
  'conductor',
  'remixer',
  'sampled',
  'engineer',
]);

type Comparison = Schemas['CompareRecordingsResponse'];
type Song = Schemas['RecordingSummary'];

function roleName(role: string): MessageId {
  return (
    KNOWN_ROLES.has(role) ? `song.role.${role}` : 'role.other'
  ) as MessageId;
}

/** How alike they sound, as a ring around the number. */
function Likeness({value}: {value: number | null}) {
  const {t} = useI18n();
  if (value === null) return null;
  return (
    <div
      className="cx-likeness"
      style={
        {
          '--pct': `${Math.round(value * 100)}%`,
          '--ring': MAGNITUDE_COLOR,
        } as CSSProperties
      }
    >
      <span className="cx-likeness__value">{percent(value)}</span>
      <span className="cx-likeness__label">{t('songCompare.alike')}</span>
    </div>
  );
}

function SideBySide({data}: {data: Comparison}) {
  const {t} = useI18n();
  const describe = useDescribe();
  const a = data.descriptorsA;
  const b = data.descriptorsB;
  const rows: [string, string, string][] = [
    [t('song.sound.tempo'), describe.tempo(a), describe.tempo(b)],
    [t('song.sound.keyLabel'), describe.key(a), describe.key(b)],
    [t('song.sound.length'), describe.length(a), describe.length(b)],
    [
      t('song.sound.loudness'),
      percent(a?.averageLoudness),
      percent(b?.averageLoudness),
    ],
    ...MOODS.filter(
      m => a?.moods[m] !== undefined || b?.moods[m] !== undefined,
    ).map(
      m =>
        [
          t(`song.mood.${m}` as MessageId),
          percent(a?.moods[m]),
          percent(b?.moods[m]),
        ] as [string, string, string],
    ),
  ];
  return (
    <div className="cx-table-wrap">
      <table className="cx-sxs">
        <thead>
          <tr>
            <th scope="col">
              <span className="visually-hidden">
                {t('songCompare.quality')}
              </span>
            </th>
            <th scope="col" style={{'--side': SIDE_COLOR.a} as CSSProperties}>
              <bdi>{data.recordingA.displayName}</bdi>
            </th>
            <th scope="col" style={{'--side': SIDE_COLOR.b} as CSSProperties}>
              <bdi>{data.recordingB.displayName}</bdi>
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([label, x, y]) => (
            <tr key={label}>
              <th scope="row">{label}</th>
              <td>{x}</td>
              <td>{y}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function People({artists}: {artists: ArtistSummary[]}) {
  return (
    <ul className="cx-people cx-people--dense">
      {artists.map(artist => (
        <li key={artist.name}>
          <Link className="cx-person" to={artistPath(artist)}>
            <Cover name={artist.displayName} image={imageOf(artist)} round />
            <span className="cx-person__name">
              <bdi>{artist.displayName}</bdi>
            </span>
          </Link>
        </li>
      ))}
    </ul>
  );
}

function Credits({data}: {data: Comparison}) {
  const {t} = useI18n();
  const shared = data.sharedCredits.filter(row => row.both.length > 0);
  const apart = data.sharedCredits.filter(
    row => row.both.length === 0 && (row.onlyA.length || row.onlyB.length),
  );
  return (
    <section className="cx-card cx-card--wide" aria-labelledby="cx-credits">
      <div className="cx-card__head">
        <h2 id="cx-credits" className="cx-card__title">
          {t('songCompare.credits')}
        </h2>
      </div>
      {shared.length === 0 && (
        <p className="cx-card__empty">{t('songCompare.noSharedCredits')}</p>
      )}
      {shared.map(row => (
        <div key={row.role} className="cx-role">
          <h3 className="cx-role__title">{t(roleName(row.role))}</h3>
          <People artists={row.both} />
        </div>
      ))}
      {apart.length > 0 && (
        <div className="cx-apart">
          {(['a', 'b'] as const).map(side => {
            const song = side === 'a' ? data.recordingA : data.recordingB;
            const rows = apart.filter(row =>
              side === 'a' ? row.onlyA.length : row.onlyB.length,
            );
            return (
              <div
                key={side}
                className="cx-apart__side"
                style={{'--side': SIDE_COLOR[side]} as CSSProperties}
              >
                <h3 className="cx-apart__title">
                  {t('songCompare.only', {name: song.displayName})}
                </h3>
                {rows.map(row => (
                  <div key={row.role} className="cx-role">
                    <h4 className="cx-role__title">{t(roleName(row.role))}</h4>
                    <People
                      artists={(side === 'a' ? row.onlyA : row.onlyB).slice(
                        0,
                        8,
                      )}
                    />
                  </div>
                ))}
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}

function ListenTo({song}: {song: Song}) {
  const {t} = useI18n();
  const formatList = useListFormat();
  const artists = formatList(song.artists.map(a => a.displayName));
  return (
    <ListenLink
      query={`${song.displayName} ${song.artists[0]?.displayName ?? ''}`}
      label={t('connect.listenToSong', {title: song.displayName, artists})}
    />
  );
}

export default function SongCompareScreen() {
  const {t} = useI18n();
  const [search, setSearch] = useSearchParams();
  const a = search.get('a');
  const b = search.get('b');
  const result = useRecordingComparison(a ?? undefined, b ?? undefined);
  usePageTitle(t('songCompare.title'));
  const data = result.data;
  useAmbient(data?.recordingA.displayName ?? null);

  function set(changes: Record<string, string | null>) {
    setSearch(
      current => {
        const next = new URLSearchParams(current);
        for (const [key, value] of Object.entries(changes)) {
          if (value) next.set(key, value);
          else next.delete(key);
        }
        return next;
      },
      {replace: true},
    );
  }

  const loading = result.isFetching && !data;

  return (
    <div className="cx cx-songs">
      <ToolHero
        overline={t('songCompare.overline')}
        icon="note"
        title={t('songCompare.title')}
        lead={t('songCompare.lead')}
      >
        <p className="cx-hero__aside">
          <Link to="/compare">{t('songCompare.artistsInstead')}</Link>
        </p>
      </ToolHero>

      <section className="cx-picker" aria-label={t('songCompare.title')}>
        <div className="cx-faceoff">
          <SongSlot
            label={t('songCompare.first')}
            song={data?.recordingA}
            loading={Boolean(a) && loading}
            side="a"
            onPick={id => set({a: id})}
          />
          <div className="cx-faceoff__middle">
            <span className="cx-faceoff__wire" aria-hidden="true" />
            {data && data.similarity !== null ? (
              <Likeness value={data.similarity} />
            ) : (
              <span className="cx-vs" aria-hidden="true">
                {t('compare.vs')}
              </span>
            )}
            <button
              type="button"
              className="icon-btn icon-btn--outlined cx-swap"
              disabled={!a && !b}
              onClick={() => set({a: b, b: a})}
            >
              <Icon name="swap" label={t('path.swap')} />
            </button>
          </div>
          <SongSlot
            label={t('songCompare.second')}
            song={data?.recordingB}
            loading={Boolean(b) && loading}
            side="b"
            onPick={id => set({b: id})}
          />
        </div>
        {data && (
          <div className="cx-picker__bar">
            <div className="cx-actions">
              <ListenTo song={data.recordingA} />
              <ListenTo song={data.recordingB} />
            </div>
            <ShareButton
              kind="RECORDING_COMPARISON"
              subjects={[data.recordingA.name, data.recordingB.name]}
              title={t('friends.share.versus', {
                a: data.recordingA.displayName,
                b: data.recordingB.displayName,
              })}
            />
          </div>
        )}
      </section>

      {(!a || !b) && (
        <Moment
          icon="note"
          title={t('songCompare.empty.title')}
          body={t('songCompare.empty.body')}
        />
      )}
      {loading && (
        <div className="cx-board" role="status">
          <span className="visually-hidden">{t('state.loading')}</span>
          {Array.from({length: 3}, (_, i) => (
            <span
              key={i}
              className="skeleton cx-skel-card"
              aria-hidden="true"
            />
          ))}
        </div>
      )}
      {result.isError && (
        <ErrorState
          error={result.error}
          onRetry={() => void result.refetch()}
        />
      )}
      {data && (
        <div className="cx-board">
          <section className="cx-card" aria-labelledby="cx-similarity">
            <div className="cx-card__head">
              <h2 id="cx-similarity" className="cx-card__title">
                {t('songCompare.similarity')}
              </h2>
              {data.similarity !== null && (
                <span className="cx-card__count">
                  {percent(data.similarity)}
                </span>
              )}
            </div>
            {data.similarity === null ? (
              <EmptyState title={t('songCompare.noData')} />
            ) : (
              <>
                <p className="cx-card__note">{t('songCompare.howMade')}</p>
                <div
                  className="cx-meters"
                  style={{'--ring': MAGNITUDE_COLOR} as CSSProperties}
                >
                  {data.parts.map(part => (
                    <Meter
                      key={part.name}
                      label={t('songCompare.part', {
                        part: t(`songCompare.part.${part.name}` as MessageId),
                        weight: Math.round(part.weight * 100),
                      })}
                      value={part.similarity}
                    />
                  ))}
                </div>
              </>
            )}
          </section>

          <section className="cx-card" aria-labelledby="cx-sxs">
            <div className="cx-card__head">
              <h2 id="cx-sxs" className="cx-card__title">
                {t('songCompare.sideBySide')}
              </h2>
            </div>
            {data.descriptorsA || data.descriptorsB ? (
              <SideBySide data={data} />
            ) : (
              <EmptyState title={t('songCompare.noData')} />
            )}
          </section>

          <Credits data={data} />

          <section
            className="cx-card cx-card--wide"
            aria-labelledby="cx-artists"
          >
            <div className="cx-card__head">
              <h2 id="cx-artists" className="cx-card__title">
                {t('songCompare.artists')}
              </h2>
            </div>
            {data.artistPath.length > 1 ? (
              <>
                <PortraitChain artists={data.artistPath} size="m" />
                <Link
                  className="btn btn--tonal btn--compact cx-card__more"
                  to={`/six-degrees?from=${idOf(data.artistPath[0]!.name)}&to=${idOf(data.artistPath[data.artistPath.length - 1]!.name)}`}
                >
                  <Icon name="route" />
                  {t('compare.openPath')}
                </Link>
              </>
            ) : (
              <p className="cx-card__empty">
                {data.recordingA.artists[0]?.name ===
                data.recordingB.artists[0]?.name
                  ? t('songCompare.sameArtist')
                  : t('songCompare.notConnected')}
              </p>
            )}
          </section>
        </div>
      )}
    </div>
  );
}
