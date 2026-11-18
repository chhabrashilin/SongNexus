/**
 * Explore: the front door to the connection web. A hero that shows what a web
 * looks like (real portraits joined by lines) with a large search to start
 * one, starting points as photo covers, and the other ways to look at how
 * artists relate (find a path, compare artists, compare songs) as tiles.
 */
import type {CSSProperties} from 'react';
import {Link, useNavigate} from 'react-router';

import {idOf} from '../api/client';
import {useAmbient} from '../app/ambient';
import {useConfigFlags} from '../app/flags';
import {useRecentArtists} from '../app/recent';
import {usePageTitle} from '../app/Shell';
import {useStarterArtists, type Starter} from '../app/starters';
import {imageOf} from '../components/ArtistRow';
import {Icon, type IconName} from '../components/Icon';
import {SearchBox} from '../components/SearchBox';
import {Cover, CoverCard, Shelf} from '../components/Shelf';
import {Portrait, SongCover, hueStyle} from '../connect/parts';
import {useI18n} from '../i18n/i18n';
import type {MessageId} from '../i18n/messages';

/** Where each portrait of the hero's web sits, in % of the art box. */
const ORBIT: readonly {x: number; y: number; size: 's' | 'm' | 'l'}[] = [
  {x: 20, y: 22, size: 'm'},
  {x: 79, y: 16, size: 'l'},
  {x: 90, y: 58, size: 's'},
  {x: 66, y: 86, size: 'm'},
  {x: 24, y: 80, size: 'l'},
  {x: 6, y: 50, size: 's'},
];
/** Lines between orbit portraits (indexes into ORBIT), besides the spokes. */
const CHORDS: readonly [number, number][] = [
  [0, 5],
  [1, 2],
  [3, 4],
  [0, 1],
];
const CENTER = {x: 50, y: 50};

/** The hero's art: a small connection web of real starting artists. */
function HeroWeb({people}: {people: Starter[]}) {
  const center = people[0];
  const orbit = people.slice(1, 1 + ORBIT.length);
  if (!center) return <div className="cx-hub__web" aria-hidden="true" />;
  return (
    <div className="cx-hub__web" aria-hidden="true">
      <svg
        className="cx-hub__lines"
        viewBox="0 0 100 100"
        preserveAspectRatio="none"
      >
        {orbit.map((_, i) => (
          <line
            key={`spoke-${i}`}
            x1={CENTER.x}
            y1={CENTER.y}
            x2={ORBIT[i]!.x}
            y2={ORBIT[i]!.y}
            style={{'--i': i} as CSSProperties}
          />
        ))}
        {CHORDS.filter(([a, b]) => orbit[a] && orbit[b]).map(([a, b]) => (
          <line
            key={`chord-${a}-${b}`}
            className="cx-hub__chord"
            x1={ORBIT[a]!.x}
            y1={ORBIT[a]!.y}
            x2={ORBIT[b]!.x}
            y2={ORBIT[b]!.y}
          />
        ))}
      </svg>
      <span
        className="cx-hub__node cx-hub__node--center"
        style={{'--x': CENTER.x, '--y': CENTER.y} as CSSProperties}
      >
        <Portrait
          name={center.displayName}
          image={imageOf(center)}
          size="xl"
          eager
        />
      </span>
      {orbit.map((artist, i) => (
        <span
          key={artist.name}
          className="cx-hub__node"
          style={
            {
              '--x': ORBIT[i]!.x,
              '--y': ORBIT[i]!.y,
              '--i': i,
            } as CSSProperties
          }
        >
          <Portrait
            name={artist.displayName}
            image={imageOf(artist)}
            size={ORBIT[i]!.size}
            eager
          />
          <span className="cx-hub__node-name">
            <bdi>{artist.displayName}</bdi>
          </span>
        </span>
      ))}
    </div>
  );
}

interface ToolTile {
  id: 'path' | 'compare' | 'songs';
  to: string;
  icon: IconName;
  title: MessageId;
  body: MessageId;
  flag: string;
}

function ToolTiles({starters}: {starters: Starter[]}) {
  const {t} = useI18n();
  const flags = useConfigFlags();
  const [a, b, c, d] = starters;
  const pathTo =
    a && c
      ? `/six-degrees?from=${idOf(a.name)}&to=${idOf(c.name)}`
      : '/six-degrees';
  const compareTo =
    b && d ? `/compare?a=${idOf(b.name)}&b=${idOf(d.name)}` : '/compare';
  const tiles: ToolTile[] = [
    {
      id: 'path',
      to: pathTo,
      icon: 'route',
      title: 'tool.path.title',
      body: 'tool.path.body',
      flag: 'sixDegrees',
    },
    {
      id: 'compare',
      to: compareTo,
      icon: 'compare',
      title: 'tool.compare.title',
      body: 'tool.compare.body',
      flag: 'compare',
    },
    {
      id: 'songs',
      to: '/compare/songs',
      icon: 'note',
      title: 'tool.songs.title',
      body: 'tool.songs.body',
      flag: 'compare',
    },
  ];
  return (
    <ul className="cx-tiles stagger">
      {tiles
        .filter(tile => flags[tile.flag] !== false)
        .map((tile, index) => (
          <li
            key={tile.id}
            className="cx-tile"
            data-tool={tile.id}
            style={{'--i': index} as CSSProperties}
          >
            <Link
              className="cx-tile__link"
              to={tile.to}
              style={hueStyle(
                tile.id === 'path'
                  ? a?.displayName
                  : tile.id === 'compare'
                    ? b?.displayName
                    : 'songs',
              )}
            >
              <span className="cx-tile__art" aria-hidden="true">
                {tile.id === 'path' && a && c && (
                  <span className="cx-tile__route">
                    <Portrait
                      name={a.displayName}
                      image={imageOf(a)}
                      size="m"
                    />
                    <span className="cx-tile__dots" />
                    <Portrait
                      name={c.displayName}
                      image={imageOf(c)}
                      size="m"
                    />
                  </span>
                )}
                {tile.id === 'compare' && b && d && (
                  <span className="cx-tile__versus">
                    <Portrait
                      name={b.displayName}
                      image={imageOf(b)}
                      side="a"
                      size="m"
                    />
                    <span className="cx-tile__vs">{t('compare.vs')}</span>
                    <Portrait
                      name={d.displayName}
                      image={imageOf(d)}
                      side="b"
                      size="m"
                    />
                  </span>
                )}
                {tile.id === 'songs' && (
                  <span className="cx-tile__songs">
                    <SongCover
                      song={{
                        displayName: a?.displayName ?? 'A',
                        artists: a ? [a] : [],
                      }}
                      icon="note"
                    />
                    <SongCover
                      song={{
                        displayName: c?.displayName ?? 'B',
                        artists: c ? [c] : [],
                      }}
                      icon="note"
                    />
                  </span>
                )}
                <span className="cx-tile__icon">
                  <Icon name={tile.icon} />
                </span>
              </span>
              <span className="cx-tile__text">
                <span className="cx-tile__title">{t(tile.title)}</span>
                <span className="cx-tile__body">{t(tile.body)}</span>
                <span className="cx-tile__example">
                  {tile.id === 'path' && a && c
                    ? t('connect.hub.tile.path.example', {
                        from: a.displayName,
                        to: c.displayName,
                      })
                    : tile.id === 'compare' && b && d
                      ? t('connect.hub.tile.compare.example', {
                          a: b.displayName,
                          b: d.displayName,
                        })
                      : tile.id === 'songs'
                        ? t('connect.hub.tile.songs.example')
                        : null}
                </span>
              </span>
              <span className="cx-tile__go" aria-hidden="true">
                <Icon name="chevron" />
              </span>
            </Link>
          </li>
        ))}
    </ul>
  );
}

const HOW = [
  {
    icon: 'person',
    title: 'connect.hub.how.1.title',
    body: 'connect.hub.how.1.body',
  },
  {
    icon: 'add',
    title: 'connect.hub.how.2.title',
    body: 'connect.hub.how.2.body',
  },
  {
    icon: 'link',
    title: 'connect.hub.how.3.title',
    body: 'connect.hub.how.3.body',
  },
] as const satisfies readonly {
  icon: IconName;
  title: MessageId;
  body: MessageId;
}[];

export default function ExploreHubScreen() {
  const {t} = useI18n();
  const navigate = useNavigate();
  const recent = useRecentArtists();
  const starters = useStarterArtists();
  usePageTitle(t('explore.title'));
  useAmbient(null);

  const quick = starters.slice(0, 5);

  return (
    <div className="cx cx-hub">
      <section className="cx-hub__hero" aria-labelledby="cx-hub-title">
        <div className="cx-hub__text">
          <p className="cx-hero__overline">
            <Icon name="explore" />
            {t('explore.hub.hero.overline')}
          </p>
          <h1 id="cx-hub-title" className="cx-hub__title">
            {t('explore.hub.hero.title')}
          </h1>
          <p className="cx-hub__body">{t('explore.hub.hero.body')}</p>
          <div className="cx-hub__search">
            <SearchBox
              label={t('explore.hub.web.search')}
              placeholder={t('connect.hub.search')}
              types={['ARTIST']}
              onPick={result => void navigate(`/explore/${idOf(result.name)}`)}
            />
          </div>
          {quick.length > 0 && (
            <div className="cx-hub__quick">
              <p className="cx-hub__quick-label" id="cx-hub-try">
                {t('explore.hub.try')}
              </p>
              <ul className="cx-hub__picks" aria-labelledby="cx-hub-try">
                {quick.map(artist => (
                  <li key={artist.name}>
                    <Link
                      className="cx-pick"
                      to={`/explore/${idOf(artist.name)}`}
                    >
                      <Cover
                        name={artist.displayName}
                        image={imageOf(artist)}
                        round
                        eager
                      />
                      <bdi>{artist.displayName}</bdi>
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
        <HeroWeb people={starters} />
      </section>

      {recent.length > 0 && (
        <Shelf
          eyebrow={t('explore.hub.recent.eyebrow')}
          title={t('explore.hub.recent.title')}
        >
          {recent.map(artist => (
            <CoverCard
              key={artist.name}
              to={`/explore/${idOf(artist.name)}`}
              title={artist.displayName}
              subtitle={t('explore.hub.starters.subtitle')}
              image={imageOf(artist)}
              round
            />
          ))}
        </Shelf>
      )}

      {starters.length > 0 ? (
        <Shelf
          eyebrow={t('explore.hub.starters.eyebrow')}
          title={t('explore.hub.starters.title')}
        >
          {starters.map(artist => (
            <CoverCard
              key={artist.name}
              to={`/explore/${idOf(artist.name)}`}
              title={artist.displayName}
              subtitle={t('explore.hub.starters.subtitle')}
              image={imageOf(artist)}
              round
            />
          ))}
        </Shelf>
      ) : (
        <div className="cx-shelf-skeleton" aria-hidden="true">
          {Array.from({length: 6}, (_, i) => (
            <span key={i} className="skeleton cx-shelf-skeleton__card" />
          ))}
        </div>
      )}

      <section className="cx-section" aria-labelledby="cx-hub-tools">
        <h2 id="cx-hub-tools" className="section-title">
          {t('explore.hub.tools')}
        </h2>
        <ToolTiles starters={starters} />
      </section>

      <section className="cx-section" aria-labelledby="cx-hub-how">
        <h2 id="cx-hub-how" className="section-title">
          {t('connect.hub.how.title')}
        </h2>
        <ol className="cx-how">
          {HOW.map((step, index) => (
            <li key={step.title} className="cx-how__step">
              <span className="cx-how__n" aria-hidden="true">
                {index + 1}
              </span>
              <span className="cx-how__text">
                <span className="cx-how__title">{t(step.title)}</span>
                <span className="cx-how__body">{t(step.body)}</span>
              </span>
            </li>
          ))}
        </ol>
        <details className="more">
          <summary>{t('explore.hub.about.summary')}</summary>
          <div className="more__body">
            <p>{t('explore.hub.about.body')}</p>
            <p>
              <Link to="/about">{t('footer.about')}</Link>
            </p>
          </div>
        </details>
      </section>
    </div>
  );
}
