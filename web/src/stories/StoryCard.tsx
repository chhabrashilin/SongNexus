/**
 * One story, filling the viewer: the people in it as large portraits joined by
 * the connection, the sentence in display type, the credit that backs it with
 * its source, and what to do next. The full credits are one tap away.
 */
import {useId, type CSSProperties, type MouseEvent} from 'react';
import {Link} from 'react-router';

import {imageOf} from '../components/ArtistRow';
import {subjectPath} from '../components/ConnectionSheet';
import {evidenceText, hostOf} from '../components/evidence';
import {Icon} from '../components/Icon';
import {Cover, hueOf} from '../components/Shelf';
import {useI18n} from '../i18n/i18n';
import type {MessageId} from '../i18n/messages';
import {ShareButton} from '../social/ShareSheet';

import {
  artistNamer,
  orderedParts,
  pathLink,
  shareSubjects,
  storyValues,
  tapStep,
  webLink,
  type Story,
} from './stories';

/** Clicks on these never count as a tap on the story's sides. */
const INTERACTIVE = 'a, button, input, summary, details, label, dialog';

export function StorySlide({
  story,
  index,
  total,
  near,
  onStep,
  onCredits,
  onShare,
}: {
  story: Story;
  index: number;
  total: number;
  /** Within a story of the one shown: load its photos now. */
  near: boolean;
  onStep: (step: -1 | 1) => void;
  onCredits: (story: Story) => void;
  onShare: (story: Story) => void;
}) {
  const {t, dir} = useI18n();
  const headingId = useId();
  const sentence = t(story.messageId as MessageId, storyValues(story));
  const parts = orderedParts(story);
  const lead = parts[0]?.artist;
  const web = webLink(story);
  const path = pathLink(story);
  const share = shareSubjects(story);
  const nameOf = artistNamer(story);
  const headline = story.credits[0];
  const subject = headline ? subjectPath(headline.subject.name) : null;

  function onClick(event: MouseEvent<HTMLElement>) {
    if ((event.target as Element).closest(INTERACTIVE)) return;
    if (window.getSelection()?.toString()) return;
    const box = event.currentTarget.getBoundingClientRect();
    const step = tapStep(event.clientX - box.left, box.width, dir);
    if (step) onStep(step);
  }

  return (
    // Tapping the sides is a pointer shortcut; the arrow keys and the
    // previous/next buttons do the same for everyone else.
    <article
      className="story"
      style={{'--hue': hueOf(lead?.displayName ?? story.name)} as CSSProperties}
      aria-labelledby={headingId}
      aria-describedby={`${headingId}-pos`}
      onClick={onClick}
    >
      <div className="story__backdrop" aria-hidden="true">
        {lead && (
          <Cover
            name={lead.displayName}
            image={near ? imageOf(lead) : null}
            eager
          />
        )}
      </div>

      <div
        className="story__stage"
        aria-hidden="true"
        data-count={parts.length}
      >
        {parts.map((part, i) => (
          <div key={part.role} className="story__node" data-role={part.role}>
            {i > 0 && <span className="story__link" />}
            <figure className="story__person">
              <Cover
                name={part.artist.displayName}
                image={near ? imageOf(part.artist) : null}
                round
                eager={near}
              />
              <figcaption>
                <bdi>{part.artist.displayName}</bdi>
              </figcaption>
            </figure>
          </div>
        ))}
      </div>

      <div className="story__text">
        <p className="story__kind">
          <Icon name="movie" size={16} />
          {t(`stories.kind.${story.kind}`)}
          <span className="story__pos" id={`${headingId}-pos`}>
            {t('stories.card', {n: index + 1, total})}
          </span>
        </p>
        <h2 className="story__sentence" id={headingId}>
          <bdi>{sentence}</bdi>
        </h2>

        {headline && (
          <figure className="story__credit">
            <figcaption className="story__credit-label">
              {t('stories.proof')}
            </figcaption>
            <p className="story__credit-text">
              <bdi>{evidenceText(headline, nameOf, t)}</bdi>
            </p>
            <p className="story__credit-links">
              {subject && (
                <Link to={subject}>
                  {t('connection.openSubject')}
                  {headline.subject.displayName
                    ? ` “${headline.subject.displayName}”`
                    : ''}
                </Link>
              )}
              {headline.sources.map(source => (
                <a
                  key={source.url}
                  href={source.url}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  {t('connection.source', {host: hostOf(source.url)})}
                  <Icon name="external" size={14} />
                </a>
              ))}
            </p>
          </figure>
        )}

        <button
          type="button"
          className="story__all"
          onClick={() => onCredits(story)}
        >
          <Icon name="info" size={18} />
          {t('stories.credits', {count: story.credits.length})}
          <span aria-hidden="true">·</span>
          {t('stories.credits.all')}
        </button>

        <div className="story__actions">
          {web && (
            <Link className="btn btn--filled" to={web}>
              <Icon name="explore" />
              {t('stories.openWeb')}
            </Link>
          )}
          {path && (
            <Link className="btn btn--tonal" to={path}>
              <Icon name="route" />
              {t('stories.findPath')}
            </Link>
          )}
          <button
            type="button"
            className="btn btn--tonal"
            onClick={() => onShare(story)}
          >
            <Icon name="share" />
            {t('stories.share')}
          </button>
          <ShareButton
            kind={share.kind}
            subjects={share.subjects}
            title={sentence}
          />
        </div>

        <p className="story__honest">{t('stories.honest')}</p>
      </div>
    </article>
  );
}
