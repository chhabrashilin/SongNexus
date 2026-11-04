/** Collaborations (R2-3, US-16): every collaboration of one artist, with a timeline and filters. */
import {Link, useParams} from 'react-router';

import {useArtist} from '../api/queries';
import {usePageTitle} from '../app/Shell';
import {CollaborationsPanel} from '../collaborations/CollaborationsPanel';
import {ErrorState, Spinner} from '../components/States';
import {useI18n} from '../i18n/i18n';

export default function CollaborationsScreen() {
  const {t} = useI18n();
  const {id = ''} = useParams();
  const artist = useArtist(id);
  usePageTitle(
    artist.data
      ? t('collab.page.title', {name: artist.data.displayName})
      : t('collab.title'),
  );
  if (artist.isPending) return <Spinner />;
  if (artist.isError)
    return (
      <ErrorState error={artist.error} onRetry={() => void artist.refetch()} />
    );
  return (
    <article className="stack" style={{gap: 'var(--space-5)'}}>
      <header className="stack" style={{gap: 'var(--space-1)'}}>
        <h1>{t('collab.page.title', {name: artist.data.displayName})}</h1>
        <Link to={`/artist/${id}`}>{t('collab.page.back')}</Link>
      </header>
      <CollaborationsPanel artistId={id} full />
    </article>
  );
}
