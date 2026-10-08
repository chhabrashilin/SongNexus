/** Home: what SongNexus is, a search, the main surfaces, and recently viewed artists. */
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
    to: '/play',
    icon: 'play',
    title: 'home.playCard.title',
    body: 'home.playCard.body',
    flag: 'play',
  },
  {
    to: '/six-degrees',
    icon: 'route',
    title: 'home.sixDegrees.title',
    body: 'home.sixDegrees.body',
  },
  {
    to: '/explore',
    icon: 'explore',
    title: 'explore.title',
    body: 'explore.lead',
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
        <h1 style={{font: 'var(--display-small)'}}>{t('home.title')}</h1>
        <p className="muted" style={{font: 'var(--body-large)'}}>
          {t('home.lead')}
        </p>
        <SearchBox
          label={t('search.label')}
          onPick={result => void navigate(resultPath(result))}
        />
      </section>

      <section className="section" aria-label={t('nav.primary')}>
        <div className="row" style={{alignItems: 'stretch'}}>
          {SURFACES.filter(s => !s.flag || flags[s.flag] !== false).map(
            surface => (
              <Link
                key={surface.to}
                to={surface.to}
                className="card"
                style={{
                  flex: '1 1 260px',
                  color: 'inherit',
                  textDecoration: 'none',
                }}
              >
                <div className="row" style={{color: 'var(--md-primary)'}}>
                  <Icon name={surface.icon} />
                  <h2>{t(surface.title)}</h2>
                </div>
                <p
                  className="muted"
                  style={{marginBlockStart: 'var(--space-2)'}}
                >
                  {t(surface.body)}
                </p>
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
