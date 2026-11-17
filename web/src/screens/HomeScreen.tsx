/**
 * Home, laid out like a music app's: a row of shortcut chips, one feature, then
 * shelves (where you left off, your top artists, places to start) and the rest
 * of what SongNexus does as quick picks.
 */
import {Link} from 'react-router';

import {idOf} from '../api/client';
import {useListening} from '../api/queries';
import {useConfigFlags} from '../app/flags';
import {useRecentArtists} from '../app/recent';
import {usePageTitle} from '../app/Shell';
import {useStarterArtists} from '../app/starters';
import {useAuth} from '../auth/AuthProvider';
import {artistPath} from '../components/ArtistRow';
import {Icon} from '../components/Icon';
import {CoverCard, Shelf} from '../components/Shelf';
import {ToolGrid, TOOLS} from '../components/Tools';
import {useI18n} from '../i18n/i18n';

const SHORTCUTS = [
  TOOLS.web!,
  TOOLS.path!,
  TOOLS.compare!,
  TOOLS.songs!,
  TOOLS.puzzle!,
  TOOLS.library!,
];
const MORE = [
  TOOLS.stories!,
  TOOLS.around!,
  TOOLS.games!,
  TOOLS.path!,
  TOOLS.compare!,
  TOOLS.songs!,
  TOOLS.library!,
  TOOLS.friends!,
];

/** A small, still connection web: what the product draws, at a glance. */
function FeatureArt() {
  const nodes: [number, number, number, number][] = [
    // x, y, radius, hue
    [200, 150, 30, 0],
    [92, 78, 18, 210],
    [318, 70, 20, 275],
    [338, 204, 16, 150],
    [86, 226, 20, 28],
    [206, 262, 14, 320],
    [30, 150, 11, 190],
    [384, 132, 11, 45],
    [262, 20, 10, 100],
  ];
  const lines: [number, number, string, number][] = [
    [0, 1, 'var(--series-1)', 4],
    [0, 2, 'var(--series-2)', 5],
    [0, 3, 'var(--series-3)', 3],
    [0, 4, 'var(--series-1)', 6],
    [0, 5, 'var(--series-2)', 2.5],
    [1, 6, 'var(--series-3)', 2],
    [4, 6, 'var(--series-1)', 2],
    [2, 7, 'var(--series-1)', 2.5],
    [3, 7, 'var(--series-2)', 2],
    [2, 8, 'var(--series-3)', 2],
    [1, 8, 'var(--series-2)', 1.5],
    [4, 5, 'var(--series-3)', 2],
  ];
  return (
    <svg
      className="feature__art"
      viewBox="0 0 414 290"
      aria-hidden="true"
      focusable="false"
    >
      <defs>
        {nodes.map(([, , , hue], index) => (
          <linearGradient
            key={index}
            id={`feature-node-${index}`}
            x1="0"
            y1="0"
            x2="1"
            y2="1"
          >
            <stop offset="0" stopColor={`hsl(${hue + 35} 85% 62%)`} />
            <stop offset="1" stopColor={`hsl(${hue - 30} 55% 18%)`} />
          </linearGradient>
        ))}
      </defs>
      {lines.map(([from, to, stroke, width], index) => (
        <line
          key={index}
          x1={nodes[from]![0]}
          y1={nodes[from]![1]}
          x2={nodes[to]![0]}
          y2={nodes[to]![1]}
          stroke={stroke}
          strokeWidth={width}
          strokeLinecap="round"
          opacity="0.75"
        />
      ))}
      {nodes.map(([cx, cy, r], index) => (
        <circle
          key={index}
          cx={cx}
          cy={cy}
          r={r}
          fill={`url(#feature-node-${index})`}
        />
      ))}
      <circle
        cx={nodes[0]![0]}
        cy={nodes[0]![1]}
        r={nodes[0]![2] + 5}
        fill="none"
        stroke="var(--brand)"
        strokeWidth="3"
      />
    </svg>
  );
}

function TopArtists() {
  const {t} = useI18n();
  const auth = useAuth();
  const listening = useListening(auth.status === 'signedIn', 20);
  const artists = listening.data?.artists ?? [];
  if (artists.length === 0) return null;
  return (
    <Shelf
      eyebrow={t('home.shelf.top.eyebrow')}
      title={t('home.shelf.top.title')}
      action={
        <Link className="btn btn--outlined btn--compact" to="/library">
          {t('action.showMore')}
        </Link>
      }
    >
      {artists.map(row => (
        <CoverCard
          key={row.artist.name}
          to={artistPath(row.artist)}
          title={row.artist.displayName}
          subtitle={t('library.listening.plays', {count: row.plays})}
          round
        />
      ))}
    </Shelf>
  );
}

export function HomeScreen() {
  const {t} = useI18n();
  const recent = useRecentArtists();
  const flags = useConfigFlags();
  const starters = useStarterArtists(flags.explore !== false);
  usePageTitle(undefined);

  return (
    <div className="home">
      <nav aria-label={t('home.shortcuts')}>
        <ul className="chips chips--scroll home__chips">
          {SHORTCUTS.filter(s => !s.flag || flags[s.flag] !== false).map(
            shortcut => (
              <li key={shortcut.id}>
                <Link className="chip" to={shortcut.to}>
                  {t(shortcut.title)}
                </Link>
              </li>
            ),
          )}
        </ul>
      </nav>

      <section className="feature">
        <div className="feature__text">
          <p className="strapline">{t('home.feature.strapline')}</p>
          <h1>{t('home.feature.title')}</h1>
          <p className="lead">{t('home.feature.body')}</p>
          <div className="feature__actions">
            {flags.explore !== false && (
              <Link className="btn btn--filled" to="/explore">
                <Icon name="explore" />
                {t('home.feature.cta')}
              </Link>
            )}
            {flags.play !== false && (
              <Link className="btn btn--outlined" to="/play">
                <Icon name="puzzle" />
                {t('home.feature.puzzle')}
              </Link>
            )}
          </div>
        </div>
        <FeatureArt />
      </section>

      {recent.length > 0 && (
        <Shelf
          eyebrow={t('home.shelf.recent.eyebrow')}
          title={t('home.recent')}
        >
          {recent.map(artist => (
            <CoverCard
              key={artist.name}
              to={artistPath(artist)}
              title={artist.displayName}
              subtitle={artist.disambiguation || t('search.type.ARTIST')}
              round
            />
          ))}
        </Shelf>
      )}

      <TopArtists />

      {starters.length > 0 && (
        <Shelf
          eyebrow={t('home.starters.eyebrow')}
          title={t('home.starters.title')}
        >
          {starters.map(artist => (
            <CoverCard
              key={artist.name}
              to={`/explore/${idOf(artist.name)}`}
              title={artist.displayName}
              subtitle={t('home.starters.subtitle')}
              round
            />
          ))}
        </Shelf>
      )}

      <section className="section" aria-labelledby="home-more">
        <h2 id="home-more" className="section-title">
          {t('home.more.title')}
        </h2>
        <ToolGrid tools={MORE} flags={flags} />
      </section>
    </div>
  );
}
