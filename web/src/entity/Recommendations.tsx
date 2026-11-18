/**
 * "If you like {artist}": explained recommendations on the artist page. A
 * shelf of photo covers; under each name, the reasons in a few words (shared
 * collaborators with the faces and names they come through, listeners in
 * common, a shared label). While loading it holds its place with skeleton
 * covers; when it fails or there is nothing to suggest it steps aside, so the
 * page never shows a hole.
 */
import {type CSSProperties} from 'react';
import {Link} from 'react-router';

import type {Schemas} from '../api/client';
import {artistPath, imageOf} from '../components/ArtistRow';
import {Icon, type IconName} from '../components/Icon';
import {Cover, Shelf} from '../components/Shelf';
import {
  artistIdFromPath,
  useIntentPrefetch,
} from '../components/useIntentPrefetch';
import {useI18n} from '../i18n/i18n';

import {useRecommendations} from './queries';
import {explain, listOf, type ReasonLine} from './reasons';

const ICON: Record<ReasonLine['kind'], IconName> = {
  SHARED_COLLABORATORS: 'people',
  LISTENERS_IN_COMMON: 'trendingUp',
  SAME_LABEL: 'album',
};

function RecommendationCard({
  recommendation,
  index,
}: {
  recommendation: Schemas['Recommendation'];
  index: number;
}) {
  const {t, locale} = useI18n();
  const {artist} = recommendation;
  const to = artistPath(artist);
  const intent = useIntentPrefetch(artistIdFromPath(to));
  const lines = explain(recommendation.reasons);
  return (
    <li
      className="cover-card rec-card"
      data-round
      style={{'--i': index} as CSSProperties}
    >
      <Link className="cover-card__link" to={to} {...intent}>
        <span className="cover-card__art">
          <Cover name={artist.displayName} image={imageOf(artist)} round />
        </span>
        <span className="cover-card__title">
          <bdi>{artist.displayName}</bdi>
        </span>
        <span className="rec-card__reasons">
          {lines.map(line => (
            <span
              key={line.kind}
              className="rec-card__reason"
              data-kind={line.kind}
            >
              <span className="rec-card__line">
                <Icon name={ICON[line.kind]} size={14} />
                {t(line.messageId, line.values)}
              </span>
              {line.via.length > 0 && (
                <span className="rec-card__via">
                  <span className="rec-card__faces" aria-hidden="true">
                    {line.via.map(person => (
                      <Cover
                        key={person.name}
                        name={person.displayName}
                        image={imageOf(person)}
                        round
                      />
                    ))}
                  </span>
                  <span className="rec-card__names">
                    {t('recommend.via', {
                      names: listOf(
                        line.via.map(person => person.displayName),
                        locale,
                      ),
                    })}
                  </span>
                </span>
              )}
            </span>
          ))}
        </span>
      </Link>
    </li>
  );
}

export function ArtistRecommendations({
  artistId,
  name,
}: {
  artistId: string;
  name: string;
}) {
  const {t} = useI18n();
  const query = useRecommendations(artistId);
  const items = (query.data?.recommendations ?? []).filter(
    r => explain(r.reasons).length > 0,
  );

  if (query.isPending) {
    return (
      <section
        className="shelf rec-skeleton"
        aria-busy="true"
        aria-label={t('recommend.title', {name})}
      >
        <span className="skeleton entity-skeleton__line" data-w="s" />
        <span
          className="skeleton entity-skeleton__line rec-skeleton__title"
          data-w="l"
        />
        <div className="rec-skeleton__track" aria-hidden="true">
          {[0, 1, 2, 3, 4, 5].map(i => (
            <span key={i} className="stack">
              <span className="skeleton entity-skeleton__cover" />
              <span className="skeleton entity-skeleton__line" data-w="m" />
              <span className="skeleton entity-skeleton__line" />
            </span>
          ))}
        </div>
      </section>
    );
  }
  if (query.isError || items.length === 0) return null;

  return (
    <div className="rec">
      <Shelf
        eyebrow={t('recommend.eyebrow')}
        title={t('recommend.title', {name})}
      >
        {items.map((recommendation, index) => (
          <RecommendationCard
            key={recommendation.artist.name}
            recommendation={recommendation}
            index={index}
          />
        ))}
      </Shelf>
    </div>
  );
}
