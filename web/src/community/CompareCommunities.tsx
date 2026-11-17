/** "Compare with another campus": the top artists two community charts share. */
import {useState} from 'react';
import {Link} from 'react-router';

import {idOf} from '../api/client';
import {
  communityId,
  useCommunityChart,
  type Community,
  type CommunityChart,
} from '../api/community';
import {ArtistRow} from '../components/ArtistRow';
import {Icon} from '../components/Icon';
import {SkeletonRows} from '../components/States';
import {useI18n} from '../i18n/i18n';

import {CommunityPicker} from './CommunityPicker';
import {overlap} from './format';

function Overlap({chart, other}: {chart: CommunityChart; other: Community}) {
  const {t} = useI18n();
  const theirs = useCommunityChart(communityId(other.name));
  if (theirs.isPending) return <SkeletonRows count={3} />;
  if (!theirs.data) return null;
  if (theirs.data.state === 'LOCKED')
    return (
      <p className="muted">
        {t('around.compare.locked', {name: other.shortName})}
      </p>
    );
  const shared = overlap(chart.artists, theirs.data.artists);
  const byName = new Map(
    chart.artists.map(row => [row.artist.name, row.artist]),
  );
  return (
    <>
      <p>
        {t('around.compare.shared', {
          count: shared.length,
          name: other.shortName,
        })}
      </p>
      <ol className="list">
        {shared.map(item => {
          const artist = byName.get(item.name);
          if (!artist) return null;
          return (
            <ArtistRow
              key={item.name}
              artist={artist}
              subtitle={t('around.compare.ranks', {
                a: item.rankA,
                b: item.rankB,
                here: chart.community.shortName,
                there: other.shortName,
              })}
              action={
                <Link
                  className="icon-btn"
                  to={`/explore/${idOf(item.name)}`}
                  aria-label={t('around.openWeb', {name: item.displayName})}
                >
                  <Icon name="explore" />
                </Link>
              }
            />
          );
        })}
      </ol>
    </>
  );
}

export function CompareCommunities({chart}: {chart: CommunityChart}) {
  const {t} = useI18n();
  const [other, setOther] = useState<Community | null>(null);
  const kind = chart.community.kind;
  return (
    <section
      className="section compare-communities"
      aria-labelledby="compare-title"
    >
      <h2 id="compare-title">{t(`around.compare.${kind}`)}</h2>
      {other ? (
        <>
          <Overlap chart={chart} other={other} />
          <button
            type="button"
            className="btn btn--text"
            onClick={() => setOther(null)}
          >
            {t('around.compare.clear')}
          </button>
        </>
      ) : (
        <CommunityPicker
          kind={kind}
          exclude={chart.community.name}
          label={t(`around.compare.${kind}`)}
          onPick={setOther}
        />
      )}
    </section>
  );
}
