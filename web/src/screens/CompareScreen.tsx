/**
 * Compare artists (S3, US-05), head to head: two portraits facing each other,
 * the overlap in the middle (who worked with both, shared genres, shared
 * audience, how they connect), and what each has on their own.
 */
import {useState, type CSSProperties} from 'react';
import {Link, useSearchParams} from 'react-router';

import {idOf, type Schemas} from '../api/client';
import {useArtist, useCompare} from '../api/queries';
import {useAmbient} from '../app/ambient';
import {isFiltered, useGenreSelection} from '../app/genreSelection';
import {usePageTitle} from '../app/Shell';
import {useStarterArtists} from '../app/starters';
import {artistPath, imageOf} from '../components/ArtistRow';
import {GenreFilter} from '../components/Filters';
import {Icon} from '../components/Icon';
import {Cover} from '../components/Shelf';
import {ErrorState} from '../components/States';
import {
  AUDIENCE_LEVELS,
  SIDE_COLOR,
  audienceLevel,
  countRows,
  pairShares,
  surprisePair,
} from '../connect/mixtape';
import {
  ArtistSlot,
  ListenLink,
  Moment,
  PortraitChain,
  ToolHero,
} from '../connect/parts';
import {useI18n} from '../i18n/i18n';
import {ShareButton} from '../social/ShareSheet';

/** Collaborators shown before "Show all". */
const MUTUAL_PREVIEW = 12;

type Comparison = Schemas['CompareArtistsResponse'];

const sideStyle = (side: 'a' | 'b', share: number) =>
  ({
    '--side': SIDE_COLOR[side],
    '--share': `${Math.max(2, Math.round(share * 100))}%`,
  }) as CSSProperties;

/** The numbers in the middle of the face-off. */
function Overlap({data}: {data: Comparison}) {
  const {t} = useI18n();
  const steps = data.path.length > 0 ? data.path.length - 1 : null;
  return (
    <dl className="cx-overlap stagger">
      <div className="cx-overlap__stat" style={{'--i': 0} as CSSProperties}>
        <dt>
          {t('compare.stat.mutual', {count: data.mutualCollaborators.length})}
        </dt>
        <dd>{data.mutualCollaborators.length}</dd>
      </div>
      <div className="cx-overlap__stat" style={{'--i': 1} as CSSProperties}>
        <dt>{t('compare.stat.genres')}</dt>
        <dd>
          {data.genreOverlap === null
            ? '–'
            : t('compare.overlap.value', {percent: data.genreOverlap})}
        </dd>
      </div>
      <div className="cx-overlap__stat" style={{'--i': 2} as CSSProperties}>
        {data.directlyConnected ? (
          <>
            <dt>{t('compare.stat.direct')}</dt>
            <dd>
              <Icon name="check" />
            </dd>
          </>
        ) : steps !== null ? (
          <>
            <dt>{t('compare.stat.steps', {count: steps})}</dt>
            <dd>{steps}</dd>
          </>
        ) : (
          <>
            <dt>{t('compare.stat.unknown')}</dt>
            <dd>–</dd>
          </>
        )}
      </div>
    </dl>
  );
}

function Mutual({data}: {data: Comparison}) {
  const {t} = useI18n();
  const [all, setAll] = useState(false);
  const people = data.mutualCollaborators;
  const shown = all ? people : people.slice(0, MUTUAL_PREVIEW);
  return (
    <section className="cx-card cx-card--wide" aria-labelledby="cx-mutual">
      <div className="cx-card__head">
        <h2 id="cx-mutual" className="cx-card__title">
          {t('compare.mutual')}
        </h2>
        {people.length > 0 && (
          <span className="cx-card__count">{people.length}</span>
        )}
      </div>
      {people.length === 0 ? (
        <p className="cx-card__empty">{t('compare.noMutual')}</p>
      ) : (
        <>
          <ul className="cx-people stagger">
            {shown.map((artist, index) => (
              <li key={artist.name} style={{'--i': index} as CSSProperties}>
                <Link className="cx-person" to={artistPath(artist)}>
                  <Cover
                    name={artist.displayName}
                    image={imageOf(artist)}
                    round
                  />
                  <span className="cx-person__name">
                    <bdi>{artist.displayName}</bdi>
                  </span>
                </Link>
              </li>
            ))}
          </ul>
          {people.length > MUTUAL_PREVIEW && (
            <button
              type="button"
              className="btn btn--outlined btn--compact cx-card__more"
              aria-expanded={all}
              onClick={() => setAll(a => !a)}
            >
              {all
                ? t('compare.mutual.less')
                : t('compare.mutual.showAll', {count: people.length})}
            </button>
          )}
        </>
      )}
    </section>
  );
}

function Genres({data}: {data: Comparison}) {
  const {t} = useI18n();
  const a = data.artistA.displayName;
  const b = data.artistB.displayName;
  const top = Math.max(
    0.0001,
    ...data.sharedGenres.flatMap(g => [g.shareA, g.shareB]),
  );
  return (
    <section className="cx-card" aria-labelledby="cx-genres">
      <div className="cx-card__head">
        <h2 id="cx-genres" className="cx-card__title">
          {t('compare.sharedGenres')}
        </h2>
        {data.genreOverlap !== null && (
          <span className="cx-card__count">
            {t('compare.overlap', {percent: data.genreOverlap})}
          </span>
        )}
      </div>
      {data.genreOverlap === null ? (
        <p className="cx-card__empty">{t('compare.noGenreData')}</p>
      ) : data.sharedGenres.length === 0 ? (
        <p className="cx-card__empty">{t('compare.genres.none')}</p>
      ) : (
        <ul className="cx-genres">
          {data.sharedGenres.map(genre => (
            <li key={genre.genre} className="cx-genre">
              <span className="cx-genre__name">{genre.displayName}</span>
              <span className="cx-genre__bars">
                <span
                  className="cx-bar"
                  style={sideStyle('a', genre.shareA / top)}
                  role="img"
                  aria-label={t('compare.genres.share', {
                    name: a,
                    percent: genre.shareA,
                  })}
                />
                <span
                  className="cx-bar"
                  style={sideStyle('b', genre.shareB / top)}
                  role="img"
                  aria-label={t('compare.genres.share', {
                    name: b,
                    percent: genre.shareB,
                  })}
                />
              </span>
            </li>
          ))}
        </ul>
      )}
      <Legend a={a} b={b} />
    </section>
  );
}

function Legend({a, b}: {a: string; b: string}) {
  return (
    <p className="cx-legend" aria-hidden="true">
      <span style={sideStyle('a', 1)}>
        <bdi>{a}</bdi>
      </span>
      <span style={sideStyle('b', 1)}>
        <bdi>{b}</bdi>
      </span>
    </p>
  );
}

function Audience({data}: {data: Comparison}) {
  const {t} = useI18n();
  const a = data.artistA.displayName;
  const b = data.artistB.displayName;
  const listening = data.listening;
  return (
    <section className="cx-card" aria-labelledby="cx-audience">
      <div className="cx-card__head">
        <h2 id="cx-audience" className="cx-card__title">
          {t('compare.audience')}
        </h2>
      </div>
      {listening ? (
        <>
          <p className="cx-audience__verdict">
            {t(`compare.audience.${listening.strength}`, {a, b})}
          </p>
          <div
            className="cx-scale"
            role="img"
            aria-label={t('compare.audience.level', {
              level: t(`compare.audience.level.${listening.strength}`),
            })}
          >
            {AUDIENCE_LEVELS.map((level, index) => (
              <span
                key={level}
                className="cx-scale__step"
                data-on={
                  index <= audienceLevel(listening.strength) || undefined
                }
              >
                <span className="cx-scale__label">
                  {t(`compare.audience.level.${level}`)}
                </span>
              </span>
            ))}
          </div>
          <AudienceBars data={data} listening={listening} />
          <p className="cx-card__note">{t('compare.audience.basis')}</p>
        </>
      ) : (
        <p className="cx-card__empty">{t('compare.audience.none')}</p>
      )}
    </section>
  );
}

function AudienceBars({
  data,
  listening,
}: {
  data: Comparison;
  listening: Schemas['ListenerOverlap'];
}) {
  const {t} = useI18n();
  const [shareA, shareB] = pairShares(
    listening.listenersA,
    listening.listenersB,
  );
  const rows = [
    {
      side: 'a' as const,
      share: shareA,
      name: data.artistA.displayName,
      listeners: listening.listenersA,
      other: data.artistB.displayName,
      rank: listening.rankBForA,
    },
    {
      side: 'b' as const,
      share: shareB,
      name: data.artistB.displayName,
      listeners: listening.listenersB,
      other: data.artistA.displayName,
      rank: listening.rankAForB,
    },
  ];
  return (
    <ul className="cx-listeners">
      {rows.map(row => (
        <li key={row.side} className="cx-listeners__row">
          <span
            className="cx-bar cx-bar--thick"
            style={sideStyle(row.side, row.share)}
          />
          <span className="cx-listeners__text">
            {t('compare.audience.counts', {
              name: row.name,
              listeners: row.listeners,
            })}
            {row.rank !== null &&
              ` · ${t('compare.audience.rank', {other: row.other, rank: row.rank})}`}
          </span>
        </li>
      ))}
    </ul>
  );
}

function HowConnected({data}: {data: Comparison}) {
  const {t} = useI18n();
  const a = idOf(data.artistA.name);
  const b = idOf(data.artistB.name);
  return (
    <section className="cx-card" aria-labelledby="cx-how">
      <div className="cx-card__head">
        <h2 id="cx-how" className="cx-card__title">
          {t('compare.path')}
        </h2>
        {data.path.length > 1 && (
          <span className="cx-card__count">
            {t('path.steps', {count: data.path.length - 1})}
          </span>
        )}
      </div>
      {data.directlyConnected && (
        <p className="cx-card__lead">{t('compare.direct')}</p>
      )}
      {data.path.length > 0 ? (
        <>
          <PortraitChain artists={data.path} size="m" />
          <Link
            className="btn btn--tonal btn--compact cx-card__more"
            to={`/six-degrees?from=${a}&to=${b}`}
          >
            <Icon name="route" />
            {t('compare.openPath')}
          </Link>
        </>
      ) : (
        <p className="cx-card__empty">{t('path.notConnected', {max: 6})}</p>
      )}
    </section>
  );
}

function OnTheirOwn({data}: {data: Comparison}) {
  const {t} = useI18n();
  const rows = countRows(data.countsA, data.countsB);
  if (rows.length === 0) return null;
  return (
    <section className="cx-card cx-card--wide" aria-labelledby="cx-own">
      <div className="cx-card__head">
        <h2 id="cx-own" className="cx-card__title">
          {t('compare.unique')}
        </h2>
      </div>
      <p className="cx-card__note">{t('compare.unique.body')}</p>
      <table className="cx-versus-table">
        <thead>
          <tr>
            <th scope="col">
              <bdi>{data.artistA.displayName}</bdi>
            </th>
            <th scope="col">
              <span className="visually-hidden">
                {t('compare.unique.kind')}
              </span>
            </th>
            <th scope="col">
              <bdi>{data.artistB.displayName}</bdi>
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map(row => {
            const [shareA, shareB] = pairShares(row.a, row.b);
            return (
              <tr key={row.kind}>
                <td className="cx-versus-table__a">
                  <span className="cx-versus-table__n">
                    {t('collab.count', {count: row.a})}
                  </span>
                  <span
                    className="cx-bar cx-bar--end"
                    style={sideStyle('a', shareA)}
                    aria-hidden="true"
                  />
                </td>
                <th scope="row">{t(`collab.tab.${row.kind}`)}</th>
                <td className="cx-versus-table__b">
                  <span
                    className="cx-bar"
                    style={sideStyle('b', shareB)}
                    aria-hidden="true"
                  />
                  <span className="cx-versus-table__n">
                    {t('collab.count', {count: row.b})}
                  </span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </section>
  );
}

function ResultSkeleton() {
  const {t} = useI18n();
  return (
    <div className="cx-board" role="status">
      <span className="visually-hidden">{t('state.loading')}</span>
      {Array.from({length: 4}, (_, i) => (
        <span key={i} className="skeleton cx-skel-card" aria-hidden="true" />
      ))}
    </div>
  );
}

export default function CompareScreen() {
  const {t} = useI18n();
  const [search, setSearch] = useSearchParams();
  const a = search.get('a');
  const b = search.get('b');
  const [genreFilter, setGenreFilter] = useGenreSelection();
  const [showFilters, setShowFilters] = useState(isFiltered(genreFilter));
  const result = useCompare(a ?? undefined, b ?? undefined, genreFilter);
  const artistA = useArtist(a ?? undefined);
  const artistB = useArtist(b ?? undefined);
  const starters = useStarterArtists();
  usePageTitle(t('compare.title'));
  useAmbient(artistA.data?.displayName ?? null);

  function set(changes: Record<string, string | null>) {
    const next = new URLSearchParams(search);
    for (const [key, value] of Object.entries(changes)) {
      if (value) next.set(key, value);
      else next.delete(key);
    }
    setSearch(next, {replace: true});
  }

  function surprise() {
    const pair = surprisePair(
      starters.map(artist => idOf(artist.name)),
      [a, b],
    );
    if (pair) set({a: pair[0], b: pair[1]});
  }

  const data = result.data;
  return (
    <div className="cx cx-compare">
      <ToolHero
        overline={t('compare.overline')}
        icon="compare"
        title={t('compare.title')}
        lead={t('compare.lead')}
      >
        <p className="cx-hero__aside">
          <Link to="/compare/songs">{t('compare.songsInstead')}</Link>
        </p>
      </ToolHero>

      <section className="cx-picker" aria-label={t('compare.title')}>
        <div className="cx-faceoff">
          <ArtistSlot
            label={t('path.from')}
            caption={t('compare.pick.empty')}
            artist={artistA.data}
            loading={Boolean(a) && artistA.isPending}
            side="a"
            onPick={id => set({a: id})}
          />
          <div className="cx-faceoff__middle">
            <span className="cx-faceoff__wire" aria-hidden="true" />
            <span className="cx-vs" aria-hidden="true">
              {t('compare.vs')}
            </span>
            <button
              type="button"
              className="icon-btn icon-btn--outlined cx-swap"
              disabled={!a && !b}
              onClick={() => set({a: b, b: a})}
            >
              <Icon name="swap" label={t('path.swap')} />
            </button>
          </div>
          <ArtistSlot
            label={t('path.to')}
            caption={t('compare.pick.empty')}
            artist={artistB.data}
            loading={Boolean(b) && artistB.isPending}
            side="b"
            onPick={id => set({b: id})}
          />
        </div>
        {data && <Overlap data={data} />}
        <div className="cx-picker__bar">
          <button
            type="button"
            className="btn btn--tonal"
            aria-expanded={showFilters}
            onClick={() => setShowFilters(open => !open)}
          >
            <Icon name="tune" />
            {t('compare.filter')}
          </button>
          <div className="cx-actions">
            <button
              type="button"
              className="btn btn--tonal"
              disabled={starters.length < 2}
              onClick={surprise}
            >
              <Icon name="spark" />
              {t('path.surprise')}
            </button>
            {data && (
              <ShareButton
                kind="ARTIST_COMPARISON"
                subjects={[data.artistA.name, data.artistB.name]}
                title={t('friends.share.versus', {
                  a: data.artistA.displayName,
                  b: data.artistB.displayName,
                })}
              />
            )}
          </div>
        </div>
        {showFilters && (
          <div className="cx-filters">
            <p className="cx-card__note">{t('compare.filterHelp')}</p>
            <GenreFilter selection={genreFilter} onChange={setGenreFilter} />
          </div>
        )}
      </section>

      {a && a === b && <p className="banner">{t('path.sameArtist')}</p>}
      {(!a || !b) && (
        <Moment
          icon="compare"
          title={t('compare.empty.title')}
          body={t('compare.empty.body')}
        >
          <button
            type="button"
            className="btn btn--filled"
            disabled={starters.length < 2}
            onClick={surprise}
          >
            <Icon name="spark" />
            {t('path.surprise')}
          </button>
        </Moment>
      )}
      {result.isFetching && !data && <ResultSkeleton />}
      {result.isError && (
        <ErrorState
          error={result.error}
          onRetry={() => void result.refetch()}
        />
      )}
      {data && (
        <div className="cx-board">
          <Mutual data={data} />
          <Genres data={data} />
          <Audience data={data} />
          <HowConnected data={data} />
          <OnTheirOwn data={data} />
          <div className="cx-listen-pair">
            <ListenLink
              query={data.artistA.displayName}
              label={t('connect.listenTo', {name: data.artistA.displayName})}
            />
            <ListenLink
              query={data.artistB.displayName}
              label={t('connect.listenTo', {name: data.artistB.displayName})}
            />
          </div>
        </div>
      )}
    </div>
  );
}
