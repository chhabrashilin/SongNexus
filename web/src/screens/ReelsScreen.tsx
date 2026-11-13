/** A first, text-led Reels surface that uses existing catalog actions. */
import {useState} from 'react';
import {Link} from 'react-router';

import {usePageTitle} from '../app/Shell';
import {Icon, type IconName} from '../components/Icon';
import {useI18n} from '../i18n/i18n';
import type {MessageId} from '../i18n/messages';

const REELS: {
  id: string;
  icon: IconName;
  title: MessageId;
  body: MessageId;
  to: string;
}[] = [
  {
    id: 'credits',
    icon: 'explore',
    title: 'reels.card.credits.title',
    body: 'reels.card.credits.body',
    to: '/discover',
  },
  {
    id: 'path',
    icon: 'route',
    title: 'reels.card.path.title',
    body: 'reels.card.path.body',
    to: '/six-degrees',
  },
  {
    id: 'sound',
    icon: 'note',
    title: 'reels.card.sound.title',
    body: 'reels.card.sound.body',
    to: '/compare/songs',
  },
];

export function ReelsScreen() {
  const {t} = useI18n();
  const [saved, setSaved] = useState<Set<string>>(new Set());
  usePageTitle(t('reels.title'));

  function toggleSaved(id: string) {
    setSaved(previous => {
      const next = new Set(previous);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  return (
    <div className="stack product-screen reels-screen">
      <section className="product-hero stack">
        <p className="product-hero__label">{t('nav.reels')}</p>
        <h1>{t('reels.title')}</h1>
        <p className="muted">{t('reels.lead')}</p>
      </section>
      <section className="reels-feed" aria-label={t('reels.title')}>
        {REELS.map(reel => {
          const isSaved = saved.has(reel.id);
          return (
            <article key={reel.id} className="reel-card">
              <span className="reel-card__icon" aria-hidden="true">
                <Icon name={reel.icon} size={32} />
              </span>
              <div className="stack">
                <h2>{t(reel.title)}</h2>
                <p>{t(reel.body)}</p>
              </div>
              <div className="row reel-card__actions">
                <Link className="btn btn--filled" to={reel.to}>
                  {t('reels.open')}
                </Link>
                <button
                  className="btn btn--outlined"
                  type="button"
                  aria-pressed={isSaved}
                  onClick={() => toggleSaved(reel.id)}
                >
                  {isSaved ? t('reels.saved') : t('reels.save')}
                </button>
              </div>
            </article>
          );
        })}
      </section>
    </div>
  );
}

export default ReelsScreen;
