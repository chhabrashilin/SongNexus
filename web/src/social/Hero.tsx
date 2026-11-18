/**
 * The hero at the top of the personal and social pages (Around you, Friends,
 * Library, You, About, Privacy): an overline, the page's largest type, one
 * line of what it is, the primary action, and art on the end side. It takes
 * the color of its subject through `--hue` (the same hash as covers).
 */
import type {CSSProperties, ReactNode} from 'react';

import {hueOf} from '../components/ArtistRow';
import {Icon, type IconName} from '../components/Icon';

export function Hero({
  overline,
  icon,
  title,
  titleId,
  body,
  actions,
  footnote,
  art,
  hue,
  compact = false,
}: {
  overline: string;
  icon?: IconName;
  title: ReactNode;
  titleId?: string;
  body?: ReactNode;
  actions?: ReactNode;
  /** A quiet line under the actions (a privacy promise, a source). */
  footnote?: ReactNode;
  /** Decorative: hidden from assistive technology. */
  art?: ReactNode;
  /** A name (hashed like a cover) or a hue in degrees. */
  hue?: string | number;
  /** A shorter hero for secondary pages (About, Privacy). */
  compact?: boolean;
}) {
  const h = typeof hue === 'number' ? hue : hue ? hueOf(hue) : undefined;
  return (
    <section
      className={compact ? 'p-hero p-hero--compact' : 'p-hero'}
      aria-labelledby={titleId}
      style={h === undefined ? undefined : ({'--hue': h} as CSSProperties)}
    >
      <div className="p-hero__text">
        <p className="stage__overline">
          {icon && <Icon name={icon} />}
          {overline}
        </p>
        <h1 className="p-hero__title" id={titleId}>
          {title}
        </h1>
        {body && <div className="p-hero__body">{body}</div>}
        {actions && <div className="p-hero__actions">{actions}</div>}
        {footnote && <div className="p-hero__footnote">{footnote}</div>}
      </div>
      {art && (
        <div className="p-hero__art" aria-hidden="true">
          {art}
        </div>
      )}
    </section>
  );
}

/** A one-line promise with a shield: "Opt-in. Counts as ranges. Never who plays what." */
export function PromiseLine({children}: {children: ReactNode}) {
  return (
    <p className="promise">
      <Icon name="shield" />
      <span>{children}</span>
    </p>
  );
}

/** Concentric rings with a pin at the center and a few listeners around it. */
export function RadarArt({names = []}: {names?: string[]}) {
  return (
    <div className="radar">
      <span className="radar__ring" />
      <span className="radar__ring" />
      <span className="radar__ring" />
      <span className="radar__pulse" />
      <span className="radar__pin">
        <Icon name="place" />
      </span>
      {names.slice(0, 5).map((name, i) => (
        <span
          key={`${name}-${i}`}
          className="radar__dot"
          data-i={i}
          style={{'--hue': hueOf(name)} as CSSProperties}
        />
      ))}
    </div>
  );
}

/** A labelled section with a large title, used on every personal page. */
export function Block({
  id,
  eyebrow,
  title,
  action,
  children,
  className,
}: {
  id: string;
  eyebrow?: string | undefined;
  title: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section
      className={className ? `block ${className}` : 'block'}
      aria-labelledby={id}
    >
      <div className="block__header">
        <div className="shelf__titles">
          {eyebrow && <p className="shelf__eyebrow">{eyebrow}</p>}
          <h2 id={id} className="block__title">
            {title}
          </h2>
        </div>
        {action && <div className="block__action">{action}</div>}
      </div>
      {children}
    </section>
  );
}
