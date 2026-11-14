/** Your music hub: keeps import and account surfaces together. */
import {Link} from 'react-router';

import {usePageTitle} from '../app/Shell';
import {Icon} from '../components/Icon';
import {useI18n} from '../i18n/i18n';

export function YourMusicScreen() {
  const {t} = useI18n();
  usePageTitle(t('yourMusic.title'));

  return (
    <div className="stack product-screen">
      <section className="product-hero stack">
        <p className="product-hero__label">{t('nav.yourMusic')}</p>
        <h1>{t('yourMusic.title')}</h1>
        <p className="muted">{t('yourMusic.lead')}</p>
      </section>
      <section className="tool-grid">
        <Link className="tool-card" to="/library">
          <span className="tool-card__icon">
            <Icon name="library" />
          </span>
          <span className="tool-card__title">
            {t('yourMusic.library.title')}
          </span>
          <span className="tool-card__body">{t('yourMusic.library.body')}</span>
        </Link>
        <Link className="tool-card" to="/friends">
          <span className="tool-card__icon">
            <Icon name="people" />
          </span>
          <span className="tool-card__title">
            {t('yourMusic.friends.title')}
          </span>
          <span className="tool-card__body">{t('yourMusic.friends.body')}</span>
        </Link>
        <Link className="tool-card" to="/you">
          <span className="tool-card__icon">
            <Icon name="person" />
          </span>
          <span className="tool-card__title">
            {t('yourMusic.profile.title')}
          </span>
          <span className="tool-card__body">{t('yourMusic.profile.body')}</span>
        </Link>
      </section>
    </div>
  );
}

export default YourMusicScreen;
