/** Compare (S3, US-05): shared genres, who worked with both, how they connect. */
import {Link, useSearchParams} from 'react-router';

import {idOf} from '../api/client';
import {useArtist, useCompare} from '../api/queries';
import {usePageTitle} from '../app/Shell';
import {ArtistRow, artistPath} from '../components/ArtistRow';
import {SearchBox} from '../components/SearchBox';
import {EmptyState, ErrorState, SkeletonRows} from '../components/States';
import {useI18n} from '../i18n/i18n';

function Picker({
  label,
  id,
  onPick,
}: {
  label: string;
  id: string | null;
  onPick: (id: string) => void;
}) {
  const artist = useArtist(id ?? undefined);
  return (
    <div className="stack" style={{gap: 'var(--space-1)', flex: '1 1 240px'}}>
      <span className="muted" style={{font: 'var(--label-large)'}}>
        {label}
      </span>
      <SearchBox
        key={artist.data?.name ?? 'empty'}
        label={label}
        types={['ARTIST']}
        clearOnPick={false}
        initialQuery={artist.data?.displayName ?? ''}
        onPick={result => onPick(idOf(result.name))}
      />
    </div>
  );
}

export default function CompareScreen() {
  const {t} = useI18n();
  const [search, setSearch] = useSearchParams();
  const a = search.get('a');
  const b = search.get('b');
  const result = useCompare(a ?? undefined, b ?? undefined);
  usePageTitle(t('compare.title'));

  function set(key: 'a' | 'b', value: string) {
    const next = new URLSearchParams(search);
    next.set(key, value);
    setSearch(next, {replace: true});
  }

  const data = result.data;
  return (
    <div className="stack" style={{gap: 'var(--space-5)'}}>
      <h1>{t('compare.title')}</h1>
      <div className="row" style={{alignItems: 'flex-end'}}>
        <Picker label={t('path.from')} id={a} onPick={id => set('a', id)} />
        <Picker label={t('path.to')} id={b} onPick={id => set('b', id)} />
      </div>
      {a && a === b && <p className="banner">{t('path.sameArtist')}</p>}
      {result.isFetching && !data && <SkeletonRows count={4} />}
      {result.isError && (
        <ErrorState
          error={result.error}
          onRetry={() => void result.refetch()}
        />
      )}
      {data && (
        <>
          <section className="section">
            <h2>{t('compare.sharedGenres')}</h2>
            {data.genreOverlap === null ? (
              <p className="muted">{t('compare.noGenreData')}</p>
            ) : (
              <>
                <p>{t('compare.overlap', {percent: data.genreOverlap})}</p>
                <div className="chips">
                  {data.sharedGenres.map(g => (
                    <span
                      key={g.genre}
                      className="chip"
                      style={{cursor: 'default'}}
                    >
                      {g.displayName}
                    </span>
                  ))}
                </div>
              </>
            )}
          </section>

          <section className="section">
            <h2>{t('compare.path')}</h2>
            {data.directlyConnected && <p>{t('compare.direct')}</p>}
            {data.path.length > 0 ? (
              <p>
                {data.path.map((artist, i) => (
                  <span key={artist.name}>
                    {i > 0 && ' → '}
                    <Link to={artistPath(artist)}>
                      <bdi>{artist.displayName}</bdi>
                    </Link>
                  </span>
                ))}
                {' · '}
                <span className="muted">
                  {t('path.steps', {count: data.path.length - 1})}
                </span>
              </p>
            ) : (
              <p className="muted">{t('path.notConnected', {max: 6})}</p>
            )}
          </section>

          <section className="section">
            <h2>{t('compare.mutual')}</h2>
            {data.mutualCollaborators.length === 0 ? (
              <EmptyState title={t('compare.noMutual')} />
            ) : (
              <ul className="list">
                {data.mutualCollaborators.map(artist => (
                  <ArtistRow key={artist.name} artist={artist} />
                ))}
              </ul>
            )}
          </section>
        </>
      )}
    </div>
  );
}
