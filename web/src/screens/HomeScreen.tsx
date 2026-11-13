/** Home: the six entry points into the SongNexus music companion. */
import {Link, useNavigate} from 'react-router';

import {useConfigFlags} from '../app/flags';
import {usePageTitle} from '../app/Shell';
import {useRecentArtists} from '../app/recent';
import {useListening} from '../api/queries';
import {useAuth} from '../auth/AuthProvider';
import {artistPath} from '../components/ArtistRow';
import {Icon, type IconName} from '../components/Icon';
import {SearchBox, resultPath} from '../components/SearchBox';
import {CoverCard, Shelf} from '../components/Shelf';
import {useI18n} from '../i18n/i18n';
import type {MessageId} from '../i18n/messages';

const SURFACES: {
  to: string;
  icon: IconName;
  title: MessageId;
  body: MessageId;
  flag?: string;
}[] = [
  {
    to: '/discover',
    icon: 'explore',
    title: 'home.hub.discover.title',
    body: 'home.hub.discover.body',
  },
  {
    to: '/guide',
    icon: 'spark',
    title: 'home.hub.guide.title',
    body: 'home.hub.guide.body',
  },
  {
    to: '/games',
    icon: 'play',
    title: 'home.hub.games.title',
    body: 'home.hub.games.body',
  },
  {
    to: '/around-you',
    icon: 'place',
    title: 'home.hub.around.title',
    body: 'home.hub.around.body',
  },
  {
    to: '/reels',
    icon: 'movie',
    title: 'home.hub.reels.title',
    body: 'home.hub.reels.body',
  },
  {
    to: '/your-music',
    icon: 'library',
    title: 'home.hub.music.title',
    body: 'home.hub.music.body',
  },
];

/** "Good morning" and friends, from the listener's own clock. */
function greeting(hour: number): MessageId {
  if (hour < 5) return 'home.greeting.night';
  if (hour < 12) return 'home.greeting.morning';
  if (hour < 18) return 'home.greeting.afternoon';
  return 'home.greeting.evening';
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
  const navigate = useNavigate();
  const recent = useRecentArtists();
  const flags = useConfigFlags();
  usePageTitle(undefined);

  return (
    <div className="stack home">
      <section className="hero">
        <p className="hero__eyebrow">{t(greeting(new Date().getHours()))}</p>
        <h1 className="hero__title">{t('home.hub.title')}</h1>
        <p className="hero__lead">{t('home.hub.lead')}</p>
        <div className="hero__search">
          <SearchBox
            label={t('search.label')}
            onPick={result => void navigate(resultPath(result))}
          />
        </div>
      </section>

      <section className="section" aria-label={t('nav.primary')}>
        <div className="hub-grid">
          {SURFACES.filter(s => !s.flag || flags[s.flag] !== false).map(
            (surface, index) => (
              <Link
                key={surface.to}
                to={surface.to}
                className="hub-card"
                data-tone={index % 6}
              >
                <span className="hub-card__icon">
                  <Icon name={surface.icon} />
                </span>
                <span className="hub-card__title">{t(surface.title)}</span>
                <span className="hub-card__body">{t(surface.body)}</span>
              </Link>
            ),
          )}
        </div>
      </section>

      <TopArtists />

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
              subtitle={artist.disambiguation || undefined}
              round
            />
          ))}
        </Shelf>
      )}
    </div>
  );
}
