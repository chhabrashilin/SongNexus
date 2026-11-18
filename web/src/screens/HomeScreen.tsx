/**
 * Home: a stage (what SongNexus is, then today's story, puzzle and challenge),
 * shortcut chips, shelves (where you left off, your top artists, places to
 * start, what the catalog surfaces) and everything else as tiles.
 */
import {useState, type CSSProperties, type ReactNode} from 'react';
import {Link} from 'react-router';

import {idOf} from '../api/client';
import {usePathChallenge, useStories} from '../api/discover';
import {useListening, usePuzzle} from '../api/queries';
import {useAmbient} from '../app/ambient';
import {useConfigFlags} from '../app/flags';
import {useRecentArtists} from '../app/recent';
import {usePageTitle} from '../app/Shell';
import {useStarterArtists, type Starter} from '../app/starters';
import {useAuth} from '../auth/AuthProvider';
import {artistPath, imageOf} from '../components/ArtistRow';
import {Icon} from '../components/Icon';
import {Cover, CoverCard, hueOf, Shelf} from '../components/Shelf';
import {Bento, TOOLS} from '../components/Tools';
import {HomeShelves} from '../home/HomeShelves';
import {useI18n} from '../i18n/i18n';
import type {MessageId} from '../i18n/messages';
import {localDate} from '../play/game';
import {storyValues, webLink} from '../stories/stories';

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
  TOOLS.games!,
  TOOLS.around!,
  TOOLS.path!,
  TOOLS.compare!,
  TOOLS.songs!,
  TOOLS.library!,
  TOOLS.friends!,
];

interface Slide {
  id: string;
  /** Names the slide in its dot's label. */
  label: string;
  /** The name whose color the slide takes. */
  hue: string;
  node: ReactNode;
}

/** Overlapping portraits of the people a slide is about. */
function StageArt({people}: {people: {displayName: string}[]}) {
  return (
    <div className="stage__art" aria-hidden="true">
      {people.slice(0, 3).map((person, index) => (
        <Cover
          key={`${person.displayName}-${index}`}
          name={person.displayName}
          image={imageOf(person)}
          round
          eager
        />
      ))}
    </div>
  );
}

/**
 * The top of Home: what the product is, then what is new today (a story, the
 * puzzle, the path challenge), one slide at a time. It never moves by itself.
 */
function Stage({slides}: {slides: Slide[]}) {
  const {t} = useI18n();
  const [index, setIndex] = useState(0);
  const current = Math.min(index, slides.length - 1);
  return (
    <section
      className="stage"
      aria-roledescription="carousel"
      aria-label={t('home.stage.label')}
    >
      {slides.map((slide, i) => (
        <div
          key={slide.id}
          className="stage__slide"
          role="group"
          aria-roledescription="slide"
          aria-label={slide.label}
          data-current={i === current || undefined}
          style={{'--hue': hueOf(slide.hue)} as CSSProperties}
        >
          {slide.node}
        </div>
      ))}
      {slides.length > 1 && (
        <div className="stage__dots">
          {slides.map((slide, i) => (
            <button
              key={slide.id}
              type="button"
              className="stage__dot"
              aria-label={t('home.stage.show', {title: slide.label})}
              aria-current={i === current}
              onClick={() => setIndex(i)}
            />
          ))}
        </div>
      )}
    </section>
  );
}

function useSlides(flags: Record<string, boolean>, starters: Starter[]) {
  const {t} = useI18n();
  const today = localDate();
  const stories = useStories(flags.stories !== false);
  const puzzle = usePuzzle(today, flags.play !== false);
  const challenge = usePathChallenge(today, flags.play !== false);
  const story = stories.data?.pages[0]?.stories?.[0];
  const p = puzzle.data;
  const c = challenge.data;

  const slides: Slide[] = [
    {
      id: 'intro',
      label: t('home.stage.intro'),
      hue: 'SongNexus',
      node: (
        <>
          <div className="stage__text">
            <p className="stage__overline">{t('home.feature.strapline')}</p>
            <h1 className="stage__title">{t('home.feature.title')}</h1>
            <p className="stage__body">{t('home.feature.body')}</p>
            <div className="stage__actions">
              {flags.explore !== false && (
                <Link className="btn btn--filled" to="/explore">
                  <Icon name="explore" />
                  {t('home.feature.cta')}
                </Link>
              )}
              {flags.play !== false && (
                <Link className="btn btn--tonal" to="/play">
                  <Icon name="puzzle" />
                  {t('home.feature.puzzle')}
                </Link>
              )}
            </div>
          </div>
          <StageArt people={starters} />
        </>
      ),
    },
  ];
  if (story) {
    const web = webLink(story);
    slides.push({
      id: 'story',
      label: t('home.stage.story'),
      hue: story.parts[0]?.artist.displayName ?? story.name,
      node: (
        <>
          <div className="stage__text">
            <p className="stage__overline">
              <Icon name="movie" />
              {t('home.stage.story')}
            </p>
            <h2 className="stage__title stage__title--long">
              <bdi>{t(story.messageId as MessageId, storyValues(story))}</bdi>
            </h2>
            <div className="stage__actions">
              {web && (
                <Link className="btn btn--filled" to={web}>
                  <Icon name="explore" />
                  {t('stories.openWeb')}
                </Link>
              )}
              <Link className="btn btn--tonal" to="/stories">
                {t('home.stage.moreStories')}
              </Link>
            </div>
          </div>
          <StageArt people={story.parts.map(part => part.artist)} />
        </>
      ),
    });
  }
  if (p) {
    slides.push({
      id: 'puzzle',
      label: t('home.stage.puzzle', {number: p.number}),
      hue: p.target.displayName,
      node: (
        <>
          <div className="stage__text">
            <p className="stage__overline">
              <Icon name="puzzle" />
              {t('home.stage.puzzle', {number: p.number})}
            </p>
            <h2 className="stage__title">
              <bdi>
                {t('home.stage.puzzle.title', {
                  start: p.start.displayName,
                  target: p.target.displayName,
                })}
              </bdi>
            </h2>
            <p className="stage__body">
              {t('home.stage.puzzle.body', {par: p.par})}
            </p>
            <div className="stage__actions">
              <Link className="btn btn--filled" to="/play">
                <Icon name="play" />
                {t('home.playCard.action')}
              </Link>
            </div>
          </div>
          <StageArt people={[p.start, p.target]} />
        </>
      ),
    });
  }
  if (c) {
    slides.push({
      id: 'challenge',
      label: t('home.stage.challenge'),
      hue: c.fromArtist.displayName,
      node: (
        <>
          <div className="stage__text">
            <p className="stage__overline">
              <Icon name="route" />
              {t('home.stage.challenge')}
            </p>
            <h2 className="stage__title">
              <bdi>
                {t('home.stage.challenge.title', {
                  from: c.fromArtist.displayName,
                  to: c.toArtist.displayName,
                  steps: c.steps,
                })}
              </bdi>
            </h2>
            <p className="stage__body">{t('home.stage.challenge.body')}</p>
            <div className="stage__actions">
              <Link
                className="btn btn--filled"
                to={`/six-degrees?from=${idOf(c.fromArtist.name)}&to=${idOf(c.toArtist.name)}`}
              >
                <Icon name="route" />
                {t('games.path.action')}
              </Link>
            </div>
          </div>
          <StageArt people={[c.fromArtist, c.toArtist]} />
        </>
      ),
    });
  }
  return slides;
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
      {artists.map((row, index) => (
        <CoverCard
          key={row.artist.name}
          to={artistPath(row.artist)}
          title={row.artist.displayName}
          subtitle={t('library.listening.plays', {count: row.plays})}
          image={imageOf(row.artist)}
          badge={index < 3 ? `#${index + 1}` : undefined}
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
  const slides = useSlides(flags, starters);
  usePageTitle(undefined);
  useAmbient(null);

  return (
    <div className="home">
      <Stage slides={slides} />

      <nav aria-label={t('home.shortcuts')}>
        <ul className="chips chips--scroll home__chips">
          {SHORTCUTS.filter(s => !s.flag || flags[s.flag] !== false).map(
            shortcut => (
              <li key={shortcut.id}>
                <Link className="chip" to={shortcut.to}>
                  <Icon name={shortcut.icon} />
                  {t(shortcut.title)}
                </Link>
              </li>
            ),
          )}
        </ul>
      </nav>

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
              image={imageOf(artist)}
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
              image={imageOf(artist)}
              round
            />
          ))}
        </Shelf>
      )}

      <HomeShelves />

      <section className="section" aria-labelledby="home-more">
        <h2 id="home-more" className="section-title">
          {t('home.more.title')}
        </h2>
        <Bento tools={MORE} flags={flags} />
      </section>
    </div>
  );
}
