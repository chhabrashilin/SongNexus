/** Discover hub: a front door for the existing catalog tools. */
import {Link, useNavigate} from 'react-router';

import {usePageTitle} from '../app/Shell';
import {Icon, type IconName} from '../components/Icon';
import {SearchBox, resultPath} from '../components/SearchBox';
import {useI18n} from '../i18n/i18n';
import type {MessageId} from '../i18n/messages';

const TOOLS: {
  to: string;
  icon: IconName;
  title: MessageId;
  body: MessageId;
}[] = [
  {
    to: '/explore',
    icon: 'explore',
    title: 'discover.explore.title',
    body: 'discover.explore.body',
  },
  {
    to: '/compare',
    icon: 'compare',
    title: 'discover.compare.title',
    body: 'discover.compare.body',
  },
  {
    to: '/compare/songs',
    icon: 'note',
    title: 'discover.songs.title',
    body: 'discover.songs.body',
  },
  {
    to: '/six-degrees',
    icon: 'route',
    title: 'discover.games.title',
    body: 'discover.games.body',
  },
];

export function DiscoverScreen() {
  const {t} = useI18n();
  const navigate = useNavigate();
  usePageTitle(t('discover.title'));

  return (
    <div className="stack product-screen">
      <section className="product-hero stack">
        <p className="product-hero__label">{t('nav.discover')}</p>
        <h1>{t('discover.title')}</h1>
        <p className="muted">{t('discover.lead')}</p>
        <SearchBox
          label={t('search.label')}
          onPick={result => void navigate(resultPath(result))}
        />
      </section>

      <section className="section">
        <div className="section__header">
          <h2>{t('discover.title')}</h2>
          <span className="muted">{t('discover.search.body')}</span>
        </div>
        <div className="tool-grid">
          {TOOLS.map(tool => (
            <Link key={tool.to} to={tool.to} className="tool-card">
              <span className="tool-card__icon">
                <Icon name={tool.icon} />
              </span>
              <span className="tool-card__title">{t(tool.title)}</span>
              <span className="tool-card__body">{t(tool.body)}</span>
              <span className="tool-card__arrow" aria-hidden="true">
                →
              </span>
            </Link>
          ))}
        </div>
      </section>
    </div>
  );
}

export default DiscoverScreen;
