/**
 * Connected services (R2-6, ADR 0006): link Spotify, YouTube Music, Last.fm,
 * ListenBrainz and others; see when each last synced; sync now; disconnect.
 *
 * Honest about timing: sync is scheduled (every N minutes) plus "Sync now",
 * never "real time". Providers that aren't set up here say so instead of
 * disappearing, and YouTube Music without a Google client offers file import.
 */
import {useEffect, useState, type FormEvent} from 'react';
import {Link, useSearchParams} from 'react-router';

import {ApiError} from '../api/client';
import {
  useLinkedAccounts,
  useLinkWithToken,
  useStartLink,
  useSyncLinkedAccount,
  useUnlinkAccount,
  type ListeningProvider,
  type ProviderOffer,
} from '../api/queries';
import {Icon} from '../components/Icon';
import {Sheet} from '../components/Sheet';
import {useSnackbar} from '../components/Snackbar';
import {SkeletonRows} from '../components/States';
import {useI18n} from '../i18n/i18n';
import type {MessageId} from '../i18n/messages';

/** Display order: the services most listeners use first. */
const ORDER: ListeningProvider[] = [
  'YOUTUBE_MUSIC',
  'SPOTIFY',
  'APPLE_MUSIC',
  'LASTFM',
  'LISTENBRAINZ',
  'DEEZER',
  'LIBREFM',
];

/** Brand-neutral monograms (no logos: we don't have the right to use them). */
const MONOGRAM: Record<ListeningProvider, string> = {
  YOUTUBE_MUSIC: 'YT',
  SPOTIFY: 'Sp',
  APPLE_MUSIC: 'Am',
  LASTFM: 'fm',
  LISTENBRAINZ: 'LB',
  DEEZER: 'Dz',
  LIBREFM: 'Lf',
};

export function providerName(
  t: (id: MessageId) => string,
  p: ListeningProvider,
) {
  return t(`accounts.provider.${p}` as MessageId);
}

function minutesSince(iso: string | null | undefined): number | null {
  if (!iso) return null;
  return Math.max(0, Math.round((Date.now() - Date.parse(iso)) / 60_000));
}

function TokenSheet({
  provider,
  onClose,
}: {
  provider: ListeningProvider | null;
  onClose: () => void;
}) {
  const {t} = useI18n();
  const snackbar = useSnackbar();
  const link = useLinkWithToken();
  const [token, setToken] = useState('');
  const name = provider ? providerName(t, provider) : '';

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!provider || !token.trim()) return;
    link.mutate(
      {provider, token: token.trim()},
      {
        onSuccess: () => {
          snackbar(t('accounts.linked', {name}));
          setToken('');
          onClose();
        },
      },
    );
  }

  return (
    <Sheet
      variant="dialog"
      open={provider !== null}
      title={t('accounts.token.title', {name})}
      onClose={onClose}
    >
      <form className="stack" onSubmit={submit}>
        <p className="muted">{t('accounts.token.body')}</p>
        <label className="stack" style={{gap: 'var(--space-1)'}}>
          <span className="label">{t('accounts.token.label')}</span>
          <span className="field">
            <input
              type="password"
              autoComplete="off"
              spellCheck={false}
              value={token}
              onChange={event => setToken(event.target.value)}
            />
          </span>
        </label>
        {link.isError && (
          <p className="banner banner--error" role="alert">
            {t('accounts.token.refused', {name})}
          </p>
        )}
        <div className="dialog__actions">
          <button type="button" className="btn btn--text" onClick={onClose}>
            {t('action.cancel')}
          </button>
          <button
            type="submit"
            className="btn btn--filled"
            disabled={!token.trim() || link.isPending}
          >
            {t('accounts.connect')}
          </button>
        </div>
      </form>
    </Sheet>
  );
}

function ServiceRow({
  offer,
  onToken,
}: {
  offer: ProviderOffer;
  onToken: (p: ListeningProvider) => void;
}) {
  const {t} = useI18n();
  const snackbar = useSnackbar();
  const start = useStartLink();
  const sync = useSyncLinkedAccount();
  const unlink = useUnlinkAccount();
  const [confirming, setConfirming] = useState(false);
  const name = providerName(t, offer.provider);
  const account = offer.linkedAccount;
  const minutes = minutesSince(account?.lastSyncTime);

  let status: string;
  if (account?.status === 'NEEDS_RELINK') status = t('accounts.needsRelink');
  else if (account && minutes === null) status = t('accounts.firstSync');
  else if (account && minutes !== null)
    status = t('accounts.syncedAgo', {minutes});
  else if (!offer.available) status = t('accounts.notOffered');
  else if (offer.method === 'FILE') status = t('accounts.fileOnly');
  else status = t(`accounts.blurb.${offer.provider}` as MessageId);

  function connect() {
    if (offer.method === 'TOKEN') return onToken(offer.provider);
    start.mutate(offer.provider, {
      onSuccess: ({authorizationUrl}) => location.assign(authorizationUrl),
      onError: () => snackbar(t('accounts.startFailed', {name})),
    });
  }

  function syncNow() {
    sync.mutate(offer.provider, {
      onSuccess: result =>
        snackbar(
          !result.synced
            ? t('accounts.syncFailed', {name})
            : result.plays === 0
              ? t('accounts.upToDate')
              : t('accounts.synced', {
                  plays: result.plays,
                  artists: result.artists,
                }),
        ),
      onError: error =>
        snackbar(
          error instanceof ApiError && error.reason === 'SYNC_TOO_SOON'
            ? t('accounts.syncTooSoon')
            : t('accounts.syncFailed', {name}),
        ),
    });
  }

  let action;
  if (account) {
    action = (
      <div className="row" style={{flexWrap: 'nowrap'}}>
        {account.status === 'NEEDS_RELINK' ? (
          <button type="button" className="btn btn--tonal" onClick={connect}>
            {t('accounts.relink')}
          </button>
        ) : (
          <button
            type="button"
            className="icon-btn"
            onClick={syncNow}
            disabled={sync.isPending}
          >
            <Icon name="sync" label={t('accounts.syncNow', {name})} />
          </button>
        )}
        <button
          type="button"
          className="icon-btn"
          onClick={() => setConfirming(true)}
        >
          <Icon name="close" label={t('accounts.disconnect', {name})} />
        </button>
      </div>
    );
  } else if (offer.method === 'FILE') {
    action = (
      <Link className="btn btn--tonal" to="/library">
        {t('accounts.import')}
      </Link>
    );
  } else if (offer.available && offer.method !== 'MUSICKIT') {
    action = (
      <button
        type="button"
        className="btn btn--tonal"
        onClick={connect}
        disabled={start.isPending}
      >
        {t('accounts.connect')}
      </button>
    );
  }

  return (
    <li className="service" data-linked={Boolean(account)}>
      <span
        className="service__mark"
        data-provider={offer.provider}
        aria-hidden="true"
      >
        {MONOGRAM[offer.provider]}
      </span>
      <span className="list-row__body">
        <span className="list-row__title">
          {name}
          {account && <span className="muted"> · {account.externalUser}</span>}
        </span>
        <span
          className="list-row__subtitle"
          data-warning={account?.status === 'NEEDS_RELINK' || undefined}
        >
          {status}
        </span>
      </span>
      {action}
      <Sheet
        variant="dialog"
        open={confirming}
        title={t('accounts.disconnect.title', {name})}
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
                unlink.mutate(offer.provider, {
                  onSuccess: () => snackbar(t('accounts.disconnected', {name})),
                });
              }}
            >
              {t('accounts.disconnect.confirm')}
            </button>
          </>
        }
      >
        <p>{t('accounts.disconnect.body', {name})}</p>
      </Sheet>
    </li>
  );
}

/** Reads ?linked= / ?linkError= after the provider sends the listener back. */
function useLinkOutcome() {
  const {t} = useI18n();
  const snackbar = useSnackbar();
  const [params, setParams] = useSearchParams();
  const linked = params.get('linked');
  const error = params.get('linkError');
  useEffect(() => {
    if (!linked && !error) return;
    if (linked && (ORDER as string[]).includes(linked))
      snackbar(
        t('accounts.linked', {
          name: providerName(t, linked as ListeningProvider),
        }),
      );
    else if (error === 'LINK_DECLINED') snackbar(t('accounts.declined'));
    else if (error) snackbar(t('accounts.linkFailed'));
    const next = new URLSearchParams(params);
    next.delete('linked');
    next.delete('linkError');
    setParams(next, {replace: true});
  }, [linked, error, params, setParams, snackbar, t]);
}

export function ConnectedServices() {
  const {t} = useI18n();
  const accounts = useLinkedAccounts(true);
  const [tokenFor, setTokenFor] = useState<ListeningProvider | null>(null);
  useLinkOutcome();

  const offers = [...(accounts.data?.providers ?? [])].sort(
    (a, b) => ORDER.indexOf(a.provider) - ORDER.indexOf(b.provider),
  );
  const linkedCount = offers.filter(o => o.linkedAccount).length;

  return (
    <section className="section" aria-labelledby="connected-title">
      <div className="section__header">
        <h2 id="connected-title">{t('accounts.title')}</h2>
        {linkedCount > 0 && (
          <span className="badge">
            {t('accounts.count', {count: linkedCount})}
          </span>
        )}
      </div>
      <p className="muted">
        {t('accounts.lead', {
          minutes: accounts.data?.syncIntervalMinutes ?? 15,
        })}
      </p>
      {accounts.isPending && <SkeletonRows count={4} />}
      {accounts.isError &&
        accounts.error instanceof ApiError &&
        accounts.error.reason === 'FLAG_OFF' && (
          <p className="muted">{t('accounts.off')}</p>
        )}
      <ul className="list services">
        {offers.map(offer => (
          <ServiceRow
            key={offer.provider}
            offer={offer}
            onToken={setTokenFor}
          />
        ))}
      </ul>
      <TokenSheet provider={tokenFor} onClose={() => setTokenFor(null)} />
    </section>
  );
}
