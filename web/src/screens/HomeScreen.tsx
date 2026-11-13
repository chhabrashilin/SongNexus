/** Home: the six entry points into the SongNexus music companion. */
import {Link, useNavigate} from 'react-router';

import {useConfigFlags} from '../app/flags';
import {usePageTitle} from '../app/Shell';
import {useRecentArtists} from '../app/recent';
import {ArtistRow} from '../components/ArtistRow';
import {Icon, type IconName} from '../components/Icon';
import {SearchBox, resultPath} from '../components/SearchBox';
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

export function HomeScreen() {
  const {t} = useI18n();
  const navigate = useNavigate();
  const recent = useRecentArtists();
  const flags = useConfigFlags();
  usePageTitle(undefined);

  return (
    <div className="stack" style={{gap: 'var(--space-6)'}}>
      <section
        className="stack"
        style={{paddingBlock: 'var(--space-5)', maxInlineSize: 720}}
      >
        <h1 style={{font: 'var(--display-small)'}}>{t('home.hub.title')}</h1>
        <p className="muted" style={{font: 'var(--body-large)'}}>
          {t('home.hub.lead')}
        </p>
        <SearchBox
          label={t('search.label')}
          onPick={result => void navigate(resultPath(result))}
        />
      </section>

      <section className="section" aria-label={t('nav.primary')}>
        <div className="hub-grid">
          {SURFACES.filter(s => !s.flag || flags[s.flag] !== false).map(
            surface => (
              <Link key={surface.to} to={surface.to} className="hub-card">
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

      {recent.length > 0 && (
        <section className="section">
          <h2>{t('home.recent')}</h2>
          <ul className="list">
            {recent.map(artist => (
              <ArtistRow key={artist.name} artist={artist} />
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
