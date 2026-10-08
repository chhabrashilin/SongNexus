/** The app frame: top bar with search and account, primary navigation, content, footer. */
import {useEffect, useRef} from 'react';
import {Link, NavLink, Outlet, useLocation, useNavigate} from 'react-router';

import {useAuth} from '../auth/AuthProvider';
import {Icon, type IconName} from '../components/Icon';
import {SearchBox, resultPath} from '../components/SearchBox';
import {Sheet} from '../components/Sheet';
import {useI18n} from '../i18n/i18n';
import type {MessageId} from '../i18n/messages';

import {useConfigFlags} from './flags';

interface NavEntry {
  to: string;
  label: MessageId;
  icon: IconName;
  flag?: string;
}

const NAV: NavEntry[] = [
  {to: '/', label: 'nav.home', icon: 'home'},
  {to: '/explore', label: 'nav.explore', icon: 'explore', flag: 'explore'},
  {
    to: '/six-degrees',
    label: 'nav.sixDegrees',
    icon: 'route',
    flag: 'sixDegrees',
  },
  {to: '/play', label: 'nav.play', icon: 'play', flag: 'play'},
  {
    to: '/library',
    label: 'nav.library',
    icon: 'library',
    flag: 'playlistImport',
  },
  {to: '/you', label: 'nav.you', icon: 'person'},
];

/** Sets the document title ("Kendrick Lamar · SongNexus"). */
export function usePageTitle(title: string | undefined) {
  const {t} = useI18n();
  useEffect(() => {
    document.title = title ? `${title} · ${t('app.name')}` : t('app.name');
  }, [title, t]);
}

function AgeConfirmation() {
  const {t} = useI18n();
  const auth = useAuth();
  return (
    <Sheet
      variant="dialog"
      open={auth.status === 'needsAgeConfirmation'}
      title={t('auth.age.title')}
      onClose={auth.cancelSignIn}
      actions={
        <>
          <button
            type="button"
            className="btn btn--text"
            onClick={auth.cancelSignIn}
          >
            {t('action.cancel')}
          </button>
          <button
            type="button"
            className="btn btn--filled"
            onClick={() => void auth.confirmAge()}
          >
            {t('auth.age.confirm')}
          </button>
        </>
      }
    >
      <p>{t('auth.age.body')}</p>
    </Sheet>
  );
}

export function Shell() {
  const {t} = useI18n();
  const navigate = useNavigate();
  const location = useLocation();
  const flags = useConfigFlags();
  const visible = NAV.filter(
    entry => !entry.flag || flags[entry.flag] !== false,
  );

  // QA Q17: after client-side navigation, put focus at the new page so screen
  // readers announce it and keyboard users start from the top.
  const firstRender = useRef(true);
  useEffect(() => {
    if (firstRender.current) {
      firstRender.current = false;
      return;
    }
    // Lazy screens render their heading a little later; wait up to ~0.5 s for it.
    let frame = 0;
    let attempts = 0;
    const focusPage = () => {
      const heading = document.querySelector<HTMLElement>('#main h1');
      if (!heading && attempts++ < 30) {
        frame = requestAnimationFrame(focusPage);
        return;
      }
      const target = heading ?? document.getElementById('main');
      if (!target) return;
      if (!target.hasAttribute('tabindex'))
        target.setAttribute('tabindex', '-1');
      target.focus();
    };
    frame = requestAnimationFrame(focusPage);
    return () => cancelAnimationFrame(frame);
  }, [location.pathname]);

  return (
    <div className="shell">
      <a className="skip-link" href="#main">
        {t('app.skipToContent')}
      </a>
      <header className="top-bar">
        <Link className="brand" to="/">
          <span className="brand__mark" aria-hidden="true" />
          <span className="brand__name">{t('app.name')}</span>
        </Link>
        {/* Home has its own, larger search; one search box per page. */}
        {location.pathname !== '/' && (
          <div className="top-bar__search">
            <SearchBox onPick={result => void navigate(resultPath(result))} />
          </div>
        )}
      </header>
      <nav className="nav" aria-label={t('nav.primary')}>
        {visible.map(entry => (
          <NavLink
            key={entry.to}
            to={entry.to}
            end={entry.to === '/'}
            className="nav__item"
          >
            <span className="nav__icon">
              <Icon name={entry.icon} />
            </span>
            {t(entry.label)}
          </NavLink>
        ))}
      </nav>
      <main id="main" className="main" tabIndex={-1}>
        <Outlet />
        <footer
          className="row muted"
          style={{
            marginBlockStart: 'var(--space-7)',
            font: 'var(--body-small)',
          }}
        >
          <Link to="/about">{t('footer.about')}</Link>
          <Link to="/privacy">{t('footer.privacy')}</Link>
        </footer>
      </main>
      <AgeConfirmation />
    </div>
  );
}
