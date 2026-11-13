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
  /** Shown in the phone bottom bar (five fit); every entry is in the sidebar. */
  phone?: boolean;
}

const NAV: NavEntry[] = [
  {to: '/', label: 'nav.home', icon: 'home', phone: true},
  {
    to: '/discover',
    label: 'nav.discover',
    icon: 'explore',
    flag: 'explore',
    phone: true,
  },
  {to: '/guide', label: 'nav.guide', icon: 'spark'},
  {to: '/games', label: 'nav.games', icon: 'play', flag: 'play', phone: true},
  {to: '/around-you', label: 'nav.aroundYou', icon: 'place'},
  {to: '/reels', label: 'nav.reels', icon: 'movie', phone: true},
  {to: '/your-music', label: 'nav.yourMusic', icon: 'library', phone: true},
];

/** Sidebar-only shortcuts to the listener's own pages. */
const PERSONAL: NavEntry[] = [
  {to: '/library', label: 'nav.library', icon: 'album'},
  {to: '/friends', label: 'nav.friends', icon: 'people', flag: 'friends'},
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

function Account() {
  const {t} = useI18n();
  const auth = useAuth();
  if (auth.status === 'signedIn')
    return (
      <Link className="account" to="/you" aria-label={t('shell.account')}>
        <span className="account__avatar" aria-hidden="true">
          <Icon name="person" />
        </span>
      </Link>
    );
  if (auth.status === 'signedOut')
    return (
      <button
        type="button"
        className="btn btn--outlined btn--compact"
        onClick={() => void auth.signIn()}
      >
        <Icon name="person" />
        {t('shell.signIn')}
      </button>
    );
  return null;
}

function NavItem({entry}: {entry: NavEntry}) {
  const {t} = useI18n();
  return (
    <NavLink
      to={entry.to}
      end={entry.to === '/'}
      className="nav__item"
      data-phone={entry.phone || undefined}
    >
      <span className="nav__icon">
        <Icon name={entry.icon} />
      </span>
      <span className="nav__label">{t(entry.label)}</span>
    </NavLink>
  );
}

export function Shell() {
  const {t} = useI18n();
  const navigate = useNavigate();
  const location = useLocation();
  const flags = useConfigFlags();
  const shown = (entry: NavEntry) => !entry.flag || flags[entry.flag] !== false;

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
          <span className="brand__mark" aria-hidden="true">
            <span />
            <span />
            <span />
          </span>
          <span className="brand__name">{t('app.name')}</span>
        </Link>
        {/* Home has its own, larger search; one search box per page. */}
        <div className="top-bar__search">
          {location.pathname !== '/' && (
            <SearchBox onPick={result => void navigate(resultPath(result))} />
          )}
        </div>
        <div className="top-bar__end">
          <Account />
        </div>
      </header>
      <nav className="nav" aria-label={t('nav.primary')}>
        <div className="nav__links">
          {NAV.filter(shown).map(entry => (
            <NavItem key={entry.to} entry={entry} />
          ))}
        </div>
        <div className="nav__extra">
          <p className="nav__heading">{t('nav.yours')}</p>
          {PERSONAL.filter(shown).map(entry => (
            <NavItem key={entry.to} entry={entry} />
          ))}
          <Link className="promo" to="/you#connected-title">
            <span className="promo__title">{t('shell.promo.title')}</span>
            <span className="promo__body">{t('shell.promo.body')}</span>
          </Link>
        </div>
      </nav>
      <main id="main" className="main" tabIndex={-1}>
        <Outlet />
        <footer className="footer row muted">
          <Link to="/about">{t('footer.about')}</Link>
          <Link to="/privacy">{t('footer.privacy')}</Link>
        </footer>
      </main>
      <AgeConfirmation />
    </div>
  );
}
