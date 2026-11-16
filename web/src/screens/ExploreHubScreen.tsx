/**
 * Explore: the front door to the connection web (pick an artist to start one)
 * and the other ways to look at how artists relate.
 */
import {Link, useNavigate} from 'react-router';

import {idOf} from '../api/client';
import {useConfigFlags} from '../app/flags';
import {useRecentArtists} from '../app/recent';
import {usePageTitle} from '../app/Shell';
import {useStarterArtists, type Starter} from '../app/starters';
import {SearchBox} from '../components/SearchBox';
import {Cover} from '../components/Shelf';
import {ToolGrid, TOOLS} from '../components/Tools';
import {useI18n} from '../i18n/i18n';

const OTHER_TOOLS = [TOOLS.path!, TOOLS.compare!, TOOLS.songs!];
/** How many "start with" suggestions fit without crowding the search. */
const SUGGESTIONS = 8;

export default function ExploreHubScreen() {
  const {t} = useI18n();
  const navigate = useNavigate();
  const flags = useConfigFlags();
  const recent = useRecentArtists();
  const starters = useStarterArtists();
  usePageTitle(t('explore.title'));

  // The listener's own recent artists first, then the editorial picks.
  const suggestions: Starter[] = [];
  for (const artist of [...recent, ...starters]) {
    if (suggestions.length >= SUGGESTIONS) break;
    if (!suggestions.some(s => s.name === artist.name))
      suggestions.push(artist);
  }

  return (
    <div className="explore-hub">
      <header className="page-header">
        <p className="strapline">{t('nav.explore')}</p>
        <h1>{t('explore.title')}</h1>
        <p className="lead">{t('explore.hub.lead')}</p>
      </header>

      <section className="web-start" aria-labelledby="web-start-title">
        <div className="web-start__text">
          <h2 id="web-start-title">{t('explore.hub.web.title')}</h2>
          <p className="lead">{t('explore.hub.web.body')}</p>
        </div>
        <div className="web-start__search">
          <SearchBox
            label={t('explore.hub.web.search')}
            placeholder={t('explore.hub.web.search')}
            types={['ARTIST']}
            onPick={result => void navigate(`/explore/${idOf(result.name)}`)}
          />
        </div>
        {suggestions.length > 0 && (
          <div className="web-start__try">
            <p className="strapline" id="web-start-try">
              {t('explore.hub.try')}
            </p>
            <ul className="web-start__picks" aria-labelledby="web-start-try">
              {suggestions.map(artist => (
                <li key={artist.name}>
                  <Link className="pick" to={`/explore/${idOf(artist.name)}`}>
                    <Cover name={artist.displayName} round />
                    <span className="pick__name">
                      <bdi>{artist.displayName}</bdi>
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        )}
      </section>

      <section className="section" aria-labelledby="explore-tools">
        <h2 id="explore-tools" className="section-title">
          {t('explore.hub.tools')}
        </h2>
        <ToolGrid tools={OTHER_TOOLS} flags={flags} />
      </section>

      <details className="more">
        <summary>{t('explore.hub.about.summary')}</summary>
        <div className="more__body">
          <p>{t('explore.hub.about.body')}</p>
          <p>
            <Link to="/about">{t('footer.about')}</Link>
          </p>
        </div>
      </details>
    </div>
  );
}
