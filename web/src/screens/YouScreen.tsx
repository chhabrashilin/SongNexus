/** You (S9): sign in, Top 5, hidden artists, theme, and data controls (US-18, US-17, US-09). */
import {useState} from 'react';

import {ApiError, idOf} from '../api/client';
import {
  useArtist,
  useBlockedArtists,
  usePreferences,
  useProfile,
  useUnblockArtist,
  useUpdatePreferences,
  useUpdateProfile,
} from '../api/queries';
import {usePageTitle} from '../app/Shell';
import {applyTheme, useTheme, type Theme} from '../app/theme';
import {useAuth} from '../auth/AuthProvider';
import {ArtistRow} from '../components/ArtistRow';
import {Icon} from '../components/Icon';
import {SearchBox} from '../components/SearchBox';
import {Sheet} from '../components/Sheet';
import {useSnackbar} from '../components/Snackbar';
import {EmptyState, SkeletonRows} from '../components/States';
import {useI18n} from '../i18n/i18n';

const MAX_TOP = 5;
const THEMES: Theme[] = ['SYSTEM', 'LIGHT', 'DARK'];

function TopFive() {
  const {t} = useI18n();
  const snackbar = useSnackbar();
  const profile = useProfile(true);
  const update = useUpdateProfile();
  const top = profile.data?.topArtists ?? [];

  function save(next: string[]) {
    if (!profile.data) return;
    update.mutate(
      {topArtists: next, etag: profile.data.etag},
      {
        onSuccess: () => snackbar(t('you.saved')),
        onError: error => {
          if (error instanceof ApiError && error.status === 'ABORTED')
            snackbar(t('you.conflict'));
        },
      },
    );
  }

  return (
    <section className="section">
      <h2>{t('you.top5')}</h2>
      <p className="muted">{t('you.top5.empty')}</p>
      {profile.isPending ? (
        <SkeletonRows count={2} />
      ) : (
        <ol className="list">
          {top.map(name => (
            <TopArtist
              key={name}
              name={name}
              onRemove={() => save(top.filter(n => n !== name))}
            />
          ))}
        </ol>
      )}
      {top.length < MAX_TOP ? (
        <SearchBox
          label={t('you.top5.add')}
          placeholder={t('you.top5.add')}
          types={['ARTIST']}
          onPick={result => {
            if (!top.includes(result.name)) save([...top, result.name]);
          }}
        />
      ) : (
        <p className="muted">{t('you.top5.full')}</p>
      )}
    </section>
  );
}

function TopArtist({name, onRemove}: {name: string; onRemove: () => void}) {
  const {t} = useI18n();
  const artist = useArtist(idOf(name));
  if (!artist.data) return <SkeletonRows count={1} />;
  return (
    <ArtistRow
      artist={artist.data}
      action={
        <button type="button" className="icon-btn" onClick={onRemove}>
          <Icon
            name="close"
            label={t('you.top5.remove', {name: artist.data.displayName})}
          />
        </button>
      }
    />
  );
}

function HiddenArtists() {
  const {t} = useI18n();
  const blocked = useBlockedArtists(true);
  const unblock = useUnblockArtist();
  const items = blocked.data?.blockedArtists ?? [];
  return (
    <section className="section">
      <h2>{t('you.blocked')}</h2>
      {blocked.isPending && <SkeletonRows count={2} />}
      {blocked.isSuccess && items.length === 0 && (
        <p className="muted">{t('you.blocked.empty')}</p>
      )}
      <ul className="list">
        {items.map(item =>
          item.artist ? (
            <ArtistRow
              key={item.name}
              artist={item.artist}
              action={
                <button
                  type="button"
                  className="btn btn--text"
                  onClick={() =>
                    unblock.mutate(item.name.split('/').pop() ?? '')
                  }
                >
                  {t('artist.unblock')}
                </button>
              }
            />
          ) : null,
        )}
      </ul>
    </section>
  );
}

function Settings({signedIn}: {signedIn: boolean}) {
  const {t} = useI18n();
  const theme = useTheme();
  const preferences = usePreferences(signedIn);
  const update = useUpdatePreferences();
  return (
    <section className="section">
      <h2>{t('you.settings')}</h2>
      <div role="radiogroup" aria-label={t('you.theme')} className="chips">
        {THEMES.map(option => (
          <button
            key={option}
            type="button"
            role="radio"
            className="chip"
            aria-checked={theme === option}
            onClick={() => {
              applyTheme(option);
              if (signedIn && preferences.data) {
                update.mutate({
                  body: {theme: option, etag: preferences.data.etag},
                  mask: 'theme',
                });
              }
            }}
          >
            {t(`you.theme.${option}`)}
          </button>
        ))}
      </div>
    </section>
  );
}

function DataControls() {
  const {t} = useI18n();
  const auth = useAuth();
  const snackbar = useSnackbar();
  const [confirming, setConfirming] = useState(false);
  return (
    <section className="section">
      <h2>{t('you.data')}</h2>
      <div className="row">
        <a
          className="btn btn--tonal"
          href="/v1/users/me:export"
          download="songnexus-data.json"
        >
          {t('you.export')}
        </a>
        <button
          type="button"
          className="btn btn--outlined"
          onClick={() => void auth.signOut()}
        >
          {t('auth.signOut')}
        </button>
        <button
          type="button"
          className="btn btn--outlined"
          onClick={() => void auth.signOutEverywhere()}
        >
          {t('auth.signOutEverywhere')}
        </button>
        <button
          type="button"
          className="btn btn--text"
          onClick={() => setConfirming(true)}
        >
          {t('you.delete')}
        </button>
      </div>
      <Sheet
        variant="dialog"
        open={confirming}
        title={t('you.delete.title')}
        onClose={() => setConfirming(false)}
        actions={
          <>
            <button
              type="button"
              className="btn btn--text"
              onClick={() => setConfirming(false)}
            >
              {t('action.cancel')}
            </button>
            <button
              type="button"
              className="btn btn--danger"
              onClick={() => {
                setConfirming(false);
                void auth
                  .deleteAccount()
                  .then(() => snackbar(t('you.deleted')));
              }}
            >
              {t('you.delete.confirm')}
            </button>
          </>
        }
      >
        <p>{t('you.delete.body')}</p>
      </Sheet>
    </section>
  );
}

export default function YouScreen() {
  const {t} = useI18n();
  const auth = useAuth();
  usePageTitle(t('you.title'));

  if (auth.status !== 'signedIn') {
    const problems = {
      failed: 'auth.failed',
      popupBlocked: 'auth.popupBlocked',
      notConfigured: 'auth.notConfigured',
    } as const;
    return (
      <div className="stack">
        <h1>{t('you.title')}</h1>
        <EmptyState
          title={t('you.signedOut')}
          action={
            <button
              type="button"
              className="btn btn--filled"
              disabled={
                auth.status === 'loading' || auth.status === 'signingIn'
              }
              onClick={() => void auth.signIn()}
            >
              {auth.status === 'signingIn'
                ? t('auth.signingIn')
                : t('auth.signIn')}
            </button>
          }
        />
        {auth.problem && (
          <p className="banner banner--error" role="alert">
            {t(problems[auth.problem])}
          </p>
        )}
        <Settings signedIn={false} />
      </div>
    );
  }

  return (
    <div className="stack" style={{gap: 'var(--space-6)'}}>
      <h1>{t('you.title')}</h1>
      <TopFive />
      <HiddenArtists />
      <Settings signedIn />
      <DataControls />
    </div>
  );
}
