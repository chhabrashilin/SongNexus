/**
 * Music-app surfaces: generated cover art, cover cards and horizontal shelves.
 *
 * We have no artwork rights, so covers are generated: a gradient whose hue is a
 * stable hash of the name, with the initial on top. The same name always gets
 * the same cover, so a listener learns to recognize it.
 */
import {useId, useRef, type CSSProperties, type ReactNode} from 'react';
import {Link} from 'react-router';

import {useI18n} from '../i18n/i18n';

import {hueOf, initialOf} from './ArtistRow';
import {Icon, type IconName} from './Icon';
import {artistIdFromPath, useIntentPrefetch} from './useIntentPrefetch';

export {hueOf};

export function Cover({
  name,
  round = false,
  icon,
}: {
  name: string;
  round?: boolean;
  /** Shown instead of the initial (for things that aren't named, like "you"). */
  icon?: IconName;
}) {
  return (
    <span
      className={round ? 'cover cover--round' : 'cover'}
      style={{'--hue': hueOf(name)} as CSSProperties}
      aria-hidden="true"
    >
      {icon ? <Icon name={icon} /> : initialOf(name)}
    </span>
  );
}

export function CoverCard({
  to,
  title,
  subtitle,
  round = false,
}: {
  to: string;
  title: string;
  subtitle?: ReactNode;
  round?: boolean;
}) {
  const intent = useIntentPrefetch(artistIdFromPath(to));
  return (
    <li className="cover-card" data-round={round || undefined}>
      <Link className="cover-card__link" to={to} {...intent}>
        <Cover name={title} round={round} />
        <span className="cover-card__title">
          <bdi>{title}</bdi>
        </span>
        {subtitle && <span className="cover-card__subtitle">{subtitle}</span>}
      </Link>
    </li>
  );
}

/** A titled, horizontally scrolling row of cards with previous/next buttons. */
export function Shelf({
  title,
  eyebrow,
  action,
  children,
}: {
  title: string;
  eyebrow?: string;
  action?: ReactNode;
  children: ReactNode;
}) {
  const {t, dir} = useI18n();
  const id = useId();
  const track = useRef<HTMLUListElement>(null);

  function page(step: 1 | -1) {
    const el = track.current;
    if (!el) return;
    const sign = dir === 'rtl' ? -1 : 1;
    el.scrollBy({
      left: step * sign * el.clientWidth * 0.85,
      behavior: 'smooth',
    });
  }

  return (
    <section className="shelf" aria-labelledby={id}>
      <div className="shelf__header">
        <div className="shelf__titles">
          {eyebrow && <p className="shelf__eyebrow">{eyebrow}</p>}
          <h2 id={id}>{title}</h2>
        </div>
        <div className="shelf__actions">
          {action}
          <button
            type="button"
            className="icon-btn icon-btn--outlined shelf__page"
            onClick={() => page(-1)}
          >
            <Icon name="chevronStart" label={t('shelf.previous')} />
          </button>
          <button
            type="button"
            className="icon-btn icon-btn--outlined shelf__page"
            onClick={() => page(1)}
          >
            <Icon name="chevron" label={t('shelf.next')} />
          </button>
        </div>
      </div>
      <ul className="shelf__track" ref={track}>
        {children}
      </ul>
    </section>
  );
}
