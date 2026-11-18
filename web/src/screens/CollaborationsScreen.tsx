/**
 * Collaborations (R2-3, US-16, v5): every collaboration of one artist, with a
 * compact hero (who, how many of each kind, over which years), the timeline
 * and the filters.
 */
import {Link, useParams} from 'react-router';

import {useArtist, useCollaborations} from '../api/queries';
import {useAmbient} from '../app/ambient';
import {NO_GENRE_FILTER} from '../app/genreSelection';
import {usePageTitle} from '../app/Shell';
import {CollaborationsPanel} from '../collaborations/CollaborationsPanel';
import {Icon} from '../components/Icon';
import {EntityError, EntityHero, EntitySkeleton, Stats} from '../entity/Entity';
import {photoOf, spanOf, spanText} from '../entity/facts';
import {useI18n} from '../i18n/i18n';

const KINDS = ['FEATURE', 'PRODUCTION', 'BAND', 'CREDIT'] as const;

export default function CollaborationsScreen() {
  const {t, formatNumber} = useI18n();
  const {id = ''} = useParams();
  const artist = useArtist(id);
  const overview = useCollaborations(id, 'FEATURE', NO_GENRE_FILTER);
  usePageTitle(
    artist.data
      ? t('collab.page.title', {name: artist.data.displayName})
      : t('collab.title'),
  );
  useAmbient(artist.data?.displayName ?? null);

  if (artist.isPending) return <EntitySkeleton kind="artist" />;
  if (artist.isError)
    return (
      <EntityError
        kind="artist"
        error={artist.error}
        onRetry={() => void artist.refetch()}
      />
    );
  const a = artist.data;
  const counts = overview.data?.counts ?? {};
  const years = spanOf((overview.data?.timeline ?? []).map(y => y.year));

  return (
    <article className="entity">
      <EntityHero
        kind="artist"
        compact
        name={a.displayName}
        photo={photoOf(a)}
        overline={t('collab.title')}
        title={t('collab.page.title', {name: a.displayName})}
        stats={
          <Stats
            label={t('collab.stat.label')}
            items={[
              ...KINDS.map(kind => ({
                key: kind,
                value:
                  counts[kind] === undefined
                    ? null
                    : formatNumber(counts[kind]),
                label: t(`collab.tab.${kind}`),
              })),
              {
                key: 'years',
                value: spanText(years),
                label: t('artist.stat.years'),
              },
            ]}
          />
        }
        actions={
          <>
            <Link className="btn btn--tonal" to={`/artist/${id}`}>
              <Icon name="back" />
              {t('collab.page.back')}
            </Link>
            <Link className="btn btn--tonal" to={`/explore/${id}`}>
              <Icon name="explore" />
              {t('artist.explore')}
            </Link>
          </>
        }
      />
      <CollaborationsPanel artistId={id} full />
    </article>
  );
}
