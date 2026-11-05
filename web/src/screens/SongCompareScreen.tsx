/** Compare songs (R2-4, S1): structure side by side, an explained similarity, shared credits. */
import {Link, useSearchParams} from 'react-router';

import {idOf, type Schemas} from '../api/client';
import {useRecording, useRecordingComparison} from '../api/queries';
import {usePageTitle} from '../app/Shell';
import {ArtistRow, artistPath} from '../components/ArtistRow';
import {SearchBox} from '../components/SearchBox';
import {EmptyState, ErrorState, SkeletonRows} from '../components/States';
import {useI18n} from '../i18n/i18n';
import type {MessageId} from '../i18n/messages';
import {MOODS, Meter, percent, useDescribe} from '../songs/Descriptors';

const KNOWN_ROLES = new Set([
  'primary',
  'featured',
  'producer',
  'vocal',
  'instrument',
  'performer',
  'programming',
  'arranger',
  'conductor',
  'remixer',
  'sampled',
  'engineer',
]);

function Picker({
  label,
  id,
  onPick,
}: {
  label: string;
  id: string | null;
  onPick: (id: string) => void;
}) {
  const song = useRecording(id ?? undefined);
  return (
    <div className="stack" style={{gap: 'var(--space-1)', flex: '1 1 240px'}}>
      <span className="muted" style={{font: 'var(--label-large)'}}>
        {label}
      </span>
      <SearchBox
        label={label}
        types={['RECORDING']}
        clearOnPick={false}
        initialQuery={song.data?.displayName ?? ''}
        onPick={result => onPick(idOf(result.name))}
      />
    </div>
  );
}

function SideBySide({data}: {data: Schemas['CompareRecordingsResponse']}) {
  const {t} = useI18n();
  const describe = useDescribe();
  const a = data.descriptorsA;
  const b = data.descriptorsB;
  const rows: [string, string, string][] = [
    [t('song.sound.tempo'), describe.tempo(a), describe.tempo(b)],
    [t('song.sound.keyLabel'), describe.key(a), describe.key(b)],
    [t('song.sound.length'), describe.length(a), describe.length(b)],
    [
      t('song.sound.loudness'),
      percent(a?.averageLoudness),
      percent(b?.averageLoudness),
    ],
    ...MOODS.filter(
      m => a?.moods[m] !== undefined || b?.moods[m] !== undefined,
    ).map(
      m =>
        [
          t(`song.mood.${m}` as MessageId),
          percent(a?.moods[m]),
          percent(b?.moods[m]),
        ] as [string, string, string],
    ),
  ];
  return (
    <table className="compare-table">
      <thead>
        <tr>
          <th scope="col">
            <span className="visually-hidden">{t('songCompare.quality')}</span>
          </th>
          <th scope="col">
            <bdi>{data.recordingA.displayName}</bdi>
          </th>
          <th scope="col">
            <bdi>{data.recordingB.displayName}</bdi>
          </th>
        </tr>
      </thead>
      <tbody>
        {rows.map(([label, x, y]) => (
          <tr key={label}>
            <th scope="row">{label}</th>
            <td>{x}</td>
            <td>{y}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function SongCompareScreen() {
  const {t} = useI18n();
  const [search, setSearch] = useSearchParams();
  const a = search.get('a');
  const b = search.get('b');
  const result = useRecordingComparison(a ?? undefined, b ?? undefined);
  usePageTitle(t('songCompare.title'));

  function set(key: 'a' | 'b', value: string) {
    setSearch(
      current => {
        const next = new URLSearchParams(current);
        next.set(key, value);
        return next;
      },
      {replace: true},
    );
  }

  const data = result.data;
  return (
    <div className="stack" style={{gap: 'var(--space-5)'}}>
      <h1>{t('songCompare.title')}</h1>
      <p className="muted">
        <Link to="/compare">{t('songCompare.artistsInstead')}</Link>
      </p>
      <div className="row" style={{alignItems: 'flex-end', flexWrap: 'wrap'}}>
        <Picker
          label={t('songCompare.first')}
          id={a}
          onPick={id => set('a', id)}
        />
        <Picker
          label={t('songCompare.second')}
          id={b}
          onPick={id => set('b', id)}
        />
      </div>
      {result.isFetching && !data && <SkeletonRows count={4} />}
      {result.isError && (
        <ErrorState
          error={result.error}
          onRetry={() => void result.refetch()}
        />
      )}
      {data && (
        <>
          <section className="section" aria-labelledby="similarity">
            <h2 id="similarity">{t('songCompare.similarity')}</h2>
            {data.similarity === null ? (
              <EmptyState title={t('songCompare.noData')} />
            ) : (
              <>
                <p className="hero-number">{percent(data.similarity)}</p>
                <p className="muted" style={{font: 'var(--body-small)'}}>
                  {t('songCompare.howMade')}
                </p>
                <div className="stack" style={{gap: 'var(--space-1)'}}>
                  {data.parts.map(part => (
                    <Meter
                      key={part.name}
                      label={t('songCompare.part', {
                        part: t(`songCompare.part.${part.name}` as MessageId),
                        weight: Math.round(part.weight * 100),
                      })}
                      value={part.similarity}
                    />
                  ))}
                </div>
              </>
            )}
          </section>

          <section className="section">
            <h2>{t('songCompare.sideBySide')}</h2>
            {data.descriptorsA || data.descriptorsB ? (
              <SideBySide data={data} />
            ) : (
              <EmptyState title={t('songCompare.noData')} />
            )}
          </section>

          <section className="section">
            <h2>{t('songCompare.credits')}</h2>
            {data.sharedCredits.every(row => row.both.length === 0) && (
              <p className="muted">{t('songCompare.noSharedCredits')}</p>
            )}
            {data.sharedCredits
              .filter(row => row.both.length > 0)
              .map(row => (
                <div
                  key={row.role}
                  className="stack"
                  style={{gap: 'var(--space-1)'}}
                >
                  <h3 className="muted" style={{font: 'var(--title-small)'}}>
                    {t(
                      (KNOWN_ROLES.has(row.role)
                        ? `song.role.${row.role}`
                        : 'role.other') as MessageId,
                    )}
                  </h3>
                  <ul className="list">
                    {row.both.map(artist => (
                      <ArtistRow key={artist.name} artist={artist} />
                    ))}
                  </ul>
                </div>
              ))}
          </section>

          <section className="section">
            <h2>{t('songCompare.artists')}</h2>
            {data.artistPath.length > 1 ? (
              <p>
                {data.artistPath.map((artist, i) => (
                  <span key={artist.name}>
                    {i > 0 && ' → '}
                    <Link to={artistPath(artist)}>
                      <bdi>{artist.displayName}</bdi>
                    </Link>
                  </span>
                ))}
              </p>
            ) : (
              <p className="muted">
                {data.recordingA.artists[0]?.name ===
                data.recordingB.artists[0]?.name
                  ? t('songCompare.sameArtist')
                  : t('songCompare.notConnected')}
              </p>
            )}
          </section>
        </>
      )}
    </div>
  );
}
