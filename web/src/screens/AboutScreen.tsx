/** About our data: where facts come from, what the licenses are, and what's missing. */
import type {Schemas} from '../api/client';
import {useDataSources} from '../api/queries';
import {usePageTitle} from '../app/Shell';
import {ErrorState, SkeletonRows} from '../components/States';
import {useI18n} from '../i18n/i18n';

const TIERS: Schemas['LicenseTier'][] = [
  'PRODUCTION',
  'NON_COMMERCIAL',
  'EVALUATION',
];

/** The data-source registry, grouped by license tier. A listener's own data is covered by Privacy. */
function Resources() {
  const {t} = useI18n();
  const sources = useDataSources();
  const listed = (sources.data ?? []).filter(s => s.kind !== 'USER_ACCOUNT');
  return (
    <section aria-labelledby="resources">
      <h2 id="resources">{t('about.resources')}</h2>
      <p>{t('about.resources.intro')}</p>
      {sources.isPending && <SkeletonRows count={4} />}
      {sources.isError && (
        <ErrorState error={sources.error} onRetry={() => sources.refetch()} />
      )}
      {TIERS.map(tier => {
        const inTier = listed.filter(s => s.tier === tier);
        if (inTier.length === 0) return null;
        return (
          <div key={tier}>
            <h3>{t(`about.resources.tier.${tier}`)}</h3>
            <ul className="stack">
              {inTier.map(source => (
                <li key={source.name}>
                  <a
                    href={source.homepage}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    {source.displayName}
                  </a>
                  {source.status === 'PLANNED' && (
                    <> ({t('about.resources.planned')})</>
                  )}
                  <br />
                  <a
                    href={source.licenseUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    {t('about.resources.license', {license: source.license})}
                  </a>
                  <br />
                  {t('about.resources.feeds', {
                    feeds: source.feeds.join('; '),
                  })}
                </li>
              ))}
            </ul>
          </div>
        );
      })}
    </section>
  );
}

export default function AboutScreen() {
  const {t} = useI18n();
  usePageTitle(t('about.title'));
  // Long-form copy is English-only in R1; it moves into the message catalog with R2 locales.
  return (
    <article className="stack" lang="en" style={{maxInlineSize: '70ch'}}>
      <h1>{t('about.title')}</h1>
      <p>
        Every connection in SongNexus comes from a published credit: who
        performed, produced, played on, sampled or engineered a recording, and
        which artists belong to which bands. Each credit links to its source so
        you can check it.
      </p>
      <h2>Where it comes from</h2>
      <p>
        Credits, artists, releases and labels come from{' '}
        <a
          href="https://musicbrainz.org"
          target="_blank"
          rel="noopener noreferrer"
        >
          MusicBrainz
        </a>
        , an open music encyclopedia maintained by volunteers. Its core data is
        in the public domain (CC0). Genres come from Discogs (public domain) and
        from MusicBrainz tags, which are licensed separately (CC BY-NC-SA 3.0)
        and kept apart from the rest of the data. Which genres sit inside which
        (trap inside hip hop) comes from Wikidata.
      </p>
      <h2>What’s missing</h2>
      <ul>
        <li>
          Our catalog covers about a hundred artists across regions and genres
          and everyone credited on their best-known albums, not every release
          ever made.
        </li>
        <li>
          “Not connected in our data yet” means exactly that. A missing credit
          is a gap in our data, not proof that two artists never worked
          together.
        </li>
        <li>
          About a third of artists have genre data. Producers and session
          players often have none, so the genre filter includes them unless you
          choose otherwise.
        </li>
      </ul>
      <h2>How strength works</h2>
      <p>
        A connection’s strength adds up the credits that link two artists. Being
        in the same band counts most, then performing together and producing,
        then contributions and samples. These weights are a starting point that
        we will calibrate with listener feedback.
      </p>
      <Resources />
    </article>
  );
}
