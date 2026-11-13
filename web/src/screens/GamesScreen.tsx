/** Games hub: groups the shipped game modes under one product surface. */
import {Link} from 'react-router';

import {usePageTitle} from '../app/Shell';
import {Icon, type IconName} from '../components/Icon';
import {useI18n} from '../i18n/i18n';
import type {MessageId} from '../i18n/messages';

const GAMES: {
  to?: string;
  icon: IconName;
  title: MessageId;
  body: MessageId;
}[] = [
  {
    to: '/play',
    icon: 'play',
    title: 'games.daily.title',
    body: 'games.daily.body',
  },
  {
    to: '/six-degrees',
    icon: 'route',
    title: 'games.path.title',
    body: 'games.path.body',
  },
  {icon: 'note', title: 'games.trivia.title', body: 'games.trivia.body'},
];

export function GamesScreen() {
  const {t} = useI18n();
  usePageTitle(t('games.title'));

  return (
    <div className="stack product-screen">
      <section className="product-hero stack">
        <p className="product-hero__label">{t('nav.games')}</p>
        <h1>{t('games.title')}</h1>
        <p className="muted">{t('games.lead')}</p>
      </section>
      <section className="tool-grid">
        {GAMES.map(game => {
          const content = (
            <>
              <span className="tool-card__icon">
                <Icon name={game.icon} />
              </span>
              <span className="tool-card__title">{t(game.title)}</span>
              <span className="tool-card__body">{t(game.body)}</span>
              {!game.to && (
                <span className="badge">{t('games.comingSoon')}</span>
              )}
            </>
          );
          return game.to ? (
            <Link key={game.title} className="tool-card" to={game.to}>
              {content}
            </Link>
          ) : (
            <div key={game.title} className="tool-card tool-card--muted">
              {content}
            </div>
          );
        })}
      </section>
    </div>
  );
}

export default GamesScreen;
