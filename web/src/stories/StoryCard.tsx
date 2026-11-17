/** One story: generated cover art, the sentence, its credits and what to do next. */
import type {CSSProperties} from 'react';
import {Link} from 'react-router';

import {EvidenceList} from '../components/ConnectionSheet';
import {Cover, hueOf} from '../components/Shelf';
import {useI18n} from '../i18n/i18n';
import type {MessageId} from '../i18n/messages';
import {ShareButton} from '../social/ShareSheet';

import {
  artistNamer,
  pathLink,
  shareSubjects,
  storyValues,
  webLink,
  type Story,
} from './stories';

export function StoryCard({
  story,
  index,
  total,
}: {
  story: Story;
  index: number;
  total: number;
}) {
  const {t} = useI18n();
  const sentence = t(story.messageId as MessageId, storyValues(story));
  const lead = story.parts[0]?.artist.displayName ?? story.name;
  const web = webLink(story);
  const path = pathLink(story);
  const share = shareSubjects(story);
  const nameOf = artistNamer(story);
  const headline = story.credits.slice(0, 1);
  return (
    <li
      className="story"
      style={{'--hue': hueOf(lead)} as CSSProperties}
      aria-label={t('stories.card', {n: index + 1, total})}
      data-story-index={index}
    >
      <div className="story__top">
        <p className="strapline">{t(`stories.kind.${story.kind}`)}</p>
        <p className="story__honest">{t('stories.honest')}</p>
      </div>
      <div className="story__covers">
        {story.parts.map(part => (
          <Cover
            key={part.role}
            name={part.artist.displayName}
            round={part.role === 'via'}
          />
        ))}
      </div>
      <div className="stack" style={{gap: 'var(--space-3)'}}>
        <h2 className="story__sentence">
          <bdi>{sentence}</bdi>
        </h2>
        <div className="story__credits">
          <EvidenceList evidence={headline} nameOf={nameOf} />
          <details className="more">
            <summary>
              {t('stories.credits', {count: story.credits.length})}
              {' · '}
              {t('stories.credits.all')}
            </summary>
            <div className="more__body">
              <EvidenceList evidence={story.credits} nameOf={nameOf} />
            </div>
          </details>
        </div>
        <div className="story__actions">
          {web && (
            <Link className="btn btn--filled" to={web}>
              {t('stories.openWeb')}
            </Link>
          )}
          {path && (
            <Link className="btn btn--tonal" to={path}>
              {t('stories.findPath')}
            </Link>
          )}
          <ShareButton
            kind={share.kind}
            subjects={share.subjects}
            title={sentence}
          />
        </div>
      </div>
    </li>
  );
}
