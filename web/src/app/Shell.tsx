/** The app frame: top bar with search and account, the guide, content, footer. */
import {useEffect, useRef, useState} from 'react';
import {Link, Outlet, useLocation, useNavigate} from 'react-router';

import {useInbox} from '../api/social';
import {useAuth} from '../auth/AuthProvider';
import {artistPath} from '../components/ArtistRow';
import {Icon, type IconName} from '../components/Icon';
import {LogoMark} from '../components/Logo';
import {SearchBox, resultPath} from '../components/SearchBox';
import {Cover} from '../components/Shelf';
import {Sheet} from '../components/Sheet';
import {useI18n} from '../i18n/i18n';
import type {MessageId} from '../i18n/messages';

import {useConfigFlags} from './flags';
import {useRecentArtists} from './recent';

interface NavEntry {
  to: string;
  label: MessageId;
  icon: IconName;
  flag?: string;
  /** Paths (besides `to`) that belong to this destination. */
  also?: string[];
}

const NAV: NavEntry[] = [
  {to: '/', label: 'nav.home', icon: 'home'},
  {
    to: '/explore',
    label: 'nav.explore',
    icon: 'explore',
    flag: 'explore',
    also: ['/six-degrees', '/compare'],
  },
  {to: '/play', label: 'nav.play', icon: 'puzzle', flag: 'play'},
  {to: '/friends', label: 'nav.friends', icon: 'people', flag: 'friends'},
  {to: '/library', label: 'nav.library', icon: 'library'},
];

/** How many recently viewed artists the guide lists. */
const GUIDE_RECENT = 6;
const RAIL_KEY = 'songnexus.guide';
/** How long to wait for a new page's heading before focusing the page itself. */
const HEADING_WAIT_MS = 4000;

function isCurrent(entry: NavEntry, pathname: string): boolean {
  if (entry.to === '/') return pathname === '/';
  return [entry.to, ...(entry.also ?? [])].some(
    path => pathname === path || pathname.startsWith(`${path}/`),
  );
}

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
        <Cover name={auth.user ?? ''} round icon="person" />
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
        <span>{t('shell.signIn')}</span>
      </button>
    );
  return null;
}

function NavItem({
  entry,
  current,
  badge = 0,
}: {
  entry: NavEntry;
  current: boolean;
  badge?: number;
}) {
  const {t} = useI18n();
  return (
    <Link
      to={entry.to}
      className="nav__item"
      aria-current={current ? 'page' : undefined}
    >
      <span className="nav__icon">
        <Icon name={entry.icon} />
        {badge > 0 && (
          <span className="nav__badge">
            {badge > 9 ? '9+' : badge}
            <span className="visually-hidden">
              {' '}
              {t('nav.friendsUnread', {count: badge})}
            </span>
          </span>
        )}
      </span>
      <span className="nav__label">{t(entry.label)}</span>
    </Link>
  );
}

function readRail(): boolean {
  try {
    return localStorage.getItem(RAIL_KEY) === 'rail';
  } catch {
    return false;
  }
}

export function Shell() {
  const {t} = useI18n();
  const navigate = useNavigate();
  const location = useLocation();
  const flags = useConfigFlags();
  const shown = (entry: NavEntry) => !entry.flag || flags[entry.flag] !== false;
  const auth = useAuth();
  const inbox = useInbox(auth.status === 'signedIn' && flags.friends !== false);
  const unread = inbox.data?.unreadCount ?? 0;
  const recent = useRecentArtists();
  const [rail, setRail] = useState(readRail);
  // The connection web fills the page: no page padding, no footer.
  const wide = /^\/explore\/[^/]+/.test(location.pathname);

  function toggleRail() {
    setRail(previous => {
      const next = !previous;
      try {
        localStorage.setItem(RAIL_KEY, next ? 'rail' : 'full');
      } catch {
        // Storage unavailable: the choice lasts for this visit.
      }
      return next;
    });
  }

  // QA Q17: after client-side navigation, put focus at the new page so screen
  // readers announce it and keyboard users start from the top.
  const firstRender = useRef(true);
  useEffect(() => {
    if (firstRender.current) {
      firstRender.current = false;
      return;
    }
    // Lazy screens render their heading later (a code chunk, then often data):
    // wait for it by the clock, not by frames, so a slow connection still gets
    // the heading. If none shows up in time, focus the page region instead.
    let frame = 0;
    const deadline = performance.now() + HEADING_WAIT_MS;
    const before = document.activeElement;
    const focusPage = () => {
      // The listener has already moved on (typing in search, say): leave them be.
      const active = document.activeElement;
      if (active && active !== before && active !== document.body) return;
      const heading = document.querySelector<HTMLElement>('#main h1');
      if (!heading && performance.now() < deadline) {
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
    <div className="shell" data-rail={rail || wide || undefined}>
      <a className="skip-link" href="#main">
        {t('app.skipToContent')}
      </a>
      <header className="top-bar">
        <div className="top-bar__start">
          <button
            type="button"
            className="icon-btn guide-toggle"
            aria-pressed={!rail}
            onClick={toggleRail}
          >
            <Icon name="menu" label={t('shell.guide')} />
          </button>
          <Link className="brand" to="/">
            <LogoMark className="brand__mark" />
            <span className="brand__name">{t('app.name')}</span>
          </Link>
        </div>
        <div className="top-bar__search">
          <SearchBox onPick={result => void navigate(resultPath(result))} />
        </div>
        <div className="top-bar__end">
          <Account />
        </div>
      </header>
      <nav className="nav" aria-label={t('nav.primary')}>
        <div className="nav__links">
          {NAV.filter(shown).map(entry => (
            <NavItem
              key={entry.to}
              entry={entry}
              current={isCurrent(entry, location.pathname)}
              badge={entry.to === '/friends' ? unread : 0}
            />
          ))}
        </div>
        <div className="nav__extra">
          {auth.status === 'signedOut' && (
            <div className="nav__prompt">
              <p>{t('shell.prompt')}</p>
              <button
                type="button"
                className="btn btn--outlined btn--compact"
                onClick={() => void auth.signIn()}
              >
                {t('shell.signIn')}
              </button>
            </div>
          )}
          {recent.length > 0 && (
            <>
              <p className="nav__heading">{t('home.recent')}</p>
              {recent.slice(0, GUIDE_RECENT).map(artist => (
                <Link
                  key={artist.name}
                  className="nav__recent"
                  to={artistPath(artist)}
                >
                  <Cover name={artist.displayName} round />
                  <span className="nav__recent-text">
                    <span className="nav__recent-name">
                      <bdi>{artist.displayName}</bdi>
                    </span>
                    <span className="nav__recent-kind">
                      {t('search.type.ARTIST')}
                    </span>
                  </span>
                </Link>
              ))}
            </>
          )}
        </div>
      </nav>
      <main
        id="main"
        className={wide ? 'main main--wide' : 'main'}
        tabIndex={-1}
      >
        <Outlet />
        {!wide && (
          <footer className="footer row muted">
            <Link to="/about">{t('footer.about')}</Link>
            <Link to="/privacy">{t('footer.privacy')}</Link>
          </footer>
        )}
      </main>
      <AgeConfirmation />
    </div>
  );
}
