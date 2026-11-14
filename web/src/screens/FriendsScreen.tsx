/**
 * Friends (R2-7): the inbox of things friends shared, the friends list,
 * invites, and the people you blocked. Friends join only through an invite
 * you send: there is no search, no contact upload and no public directory.
 */
import {useState, type FormEvent} from 'react';
import {Link, useNavigate} from 'react-router';

import {ApiError} from '../api/client';
import {
  useBlockedUsers,
  useBlockUser,
  useCreateInvite,
  useDeleteFriend,
  useDeleteInvite,
  useDeleteShare,
  useFriendInvites,
  useFriends,
  useInbox,
  useMarkInboxRead,
  useMarkShareRead,
  useReport,
  useSocialProfile,
  useUnblockUser,
  useUpdateSocialProfile,
  type ReportReason,
  type Share,
} from '../api/social';
import {useConfigFlags} from '../app/flags';
import {usePageTitle} from '../app/Shell';
import {useAuth} from '../auth/AuthProvider';
import {Icon} from '../components/Icon';
import {Sheet} from '../components/Sheet';
import {Cover} from '../components/Shelf';
import {useSnackbar} from '../components/Snackbar';
import {EmptyState, SkeletonRows} from '../components/States';
import {useI18n} from '../i18n/i18n';
import type {MessageId} from '../i18n/messages';
import {sharePath} from '../social/ShareSheet';

type Translate = ReturnType<typeof useI18n>['t'];

/** "5 minutes ago", "3 hours ago", "2 days ago". */
export function ago(t: Translate, iso: string, now = Date.now()): string {
  const minutes = Math.max(0, Math.round((now - Date.parse(iso)) / 60_000));
  if (minutes < 60) return t('friends.ago.minutes', {count: minutes});
  const hours = Math.round(minutes / 60);
  if (hours < 48) return t('friends.ago.hours', {count: hours});
  return t('friends.ago.days', {count: Math.round(hours / 24)});
}

/** What a share is about, in a few words ("Alice vs Bob", "Alice → Bob"). */
export function shareTitle(t: Translate, share: Share): string {
  const [a, b] = share.subjects.map(
    s => s.displayName || t('friends.share.gone'),
  );
  if (share.kind === 'PATH') return t('friends.share.path', {a, b});
  if (b !== undefined) return t('friends.share.versus', {a, b});
  return a ?? '';
}

export function NameCard({lead}: {lead?: string}) {
  const {t} = useI18n();
  const update = useUpdateSocialProfile();
  const [name, setName] = useState('');
  const reason = update.error instanceof ApiError ? update.error.reason : '';

  function submit(event: FormEvent) {
    event.preventDefault();
    if (name.trim()) update.mutate(name.trim());
  }

  return (
    <form className="card stack name-card" onSubmit={submit}>
      <h2>{t('friends.name.title')}</h2>
      <p className="muted">{lead ?? t('friends.name.body')}</p>
      <label className="visually-hidden" htmlFor="display-name">
        {t('friends.name.label')}
      </label>
      <div className="row" style={{flexWrap: 'nowrap'}}>
        <span className="field" style={{flex: 1}}>
          <input
            id="display-name"
            maxLength={40}
            autoComplete="nickname"
            placeholder={t('friends.name.placeholder')}
            value={name}
            onChange={event => setName(event.target.value)}
          />
        </span>
        <button
          type="submit"
          className="btn btn--filled"
          disabled={!name.trim() || update.isPending}
        >
          {t('action.save')}
        </button>
      </div>
      {update.isError && (
        <p className="banner banner--error" role="alert">
          {reason === 'TEXT_HAS_LINK'
            ? t('share.error.link')
            : t('share.error.text')}
        </p>
      )}
    </form>
  );
}

const REASONS: ReportReason[] = [
  'SPAM',
  'HARASSMENT',
  'HATE',
  'SEXUAL_CONTENT',
  'OTHER',
];

/** Report a share or a person; optionally block them in the same step. */
function ReportSheet({
  target,
  onClose,
}: {
  target: {share?: Share; user?: string; name: string} | null;
  onClose: () => void;
}) {
  const {t} = useI18n();
  const snackbar = useSnackbar();
  const report = useReport();
  const block = useBlockUser();
  const [reason, setReason] = useState<ReportReason | null>(null);
  const [alsoBlock, setAlsoBlock] = useState(true);

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!target || !reason) return;
    const person = target.share?.sender.user ?? target.user ?? '';
    report.mutate(
      target.share
        ? {share: target.share.name, reason}
        : {user: person, reason},
      {
        onSuccess: () => {
          if (alsoBlock && person) block.mutate(person);
          snackbar(t('friends.report.done'));
          setReason(null);
          onClose();
        },
      },
    );
  }

  return (
    <Sheet
      variant="dialog"
      open={target !== null}
      title={t('friends.report.title', {name: target?.name ?? ''})}
      onClose={onClose}
    >
      <form className="stack" onSubmit={submit}>
        <p className="muted">{t('friends.report.body')}</p>
        <fieldset className="stack" style={{gap: 'var(--space-1)'}}>
          <legend className="visually-hidden">
            {t('friends.report.reason')}
          </legend>
          {REASONS.map(r => (
            <label key={r} className="choice">
              <input
                type="radio"
                name="reason"
                checked={reason === r}
                onChange={() => setReason(r)}
              />
              {t(`friends.report.reason.${r}` as MessageId)}
            </label>
          ))}
        </fieldset>
        <label className="choice">
          <input
            type="checkbox"
            checked={alsoBlock}
            onChange={event => setAlsoBlock(event.target.checked)}
          />
          {t('friends.report.block', {name: target?.name ?? ''})}
        </label>
        <div className="dialog__actions">
          <button type="button" className="btn btn--text" onClick={onClose}>
            {t('action.cancel')}
          </button>
          <button
            type="submit"
            className="btn btn--danger"
            disabled={!reason || report.isPending}
          >
            {t('friends.report.send')}
          </button>
        </div>
      </form>
    </Sheet>
  );
}

function ShareCard({
  share,
  onReport,
}: {
  share: Share;
  onReport: (share: Share) => void;
}) {
  const {t} = useI18n();
  const snackbar = useSnackbar();
  const markRead = useMarkShareRead();
  const remove = useDeleteShare();
  const block = useBlockUser();
  const [options, setOptions] = useState(false);
  const title = shareTitle(t, share);
  const available = share.subjects.every(s => s.available);
  const sender = share.sender.displayName;

  return (
    <li className="share-card" data-unread={!share.read || undefined}>
      <Cover name={share.subjects[0]?.displayName || title} />
      <div className="share-card__body">
        <p className="share-card__meta">
          <span className="share-card__kind">
            {t(`share.kind.${share.kind}` as MessageId)}
          </span>
          <span>
            {t('friends.share.from', {
              name: sender,
              when: ago(t, share.createTime),
            })}
          </span>
        </p>
        <p className="share-card__title">
          <bdi>{title}</bdi>
        </p>
        {share.note && (
          <p className="share-card__note">
            <bdi>{share.note}</bdi>
          </p>
        )}
        <div className="row">
          {available ? (
            <Link
              className="btn btn--filled btn--compact"
              to={sharePath(
                share.kind,
                share.subjects.map(s => s.name),
              )}
              onClick={() => !share.read && markRead.mutate(share.name)}
            >
              <Icon name="play" />
              {t('friends.share.open')}
            </Link>
          ) : (
            <span className="muted">{t('friends.share.unavailable')}</span>
          )}
          {!share.read && (
            <button
              type="button"
              className="btn btn--text btn--compact"
              onClick={() => markRead.mutate(share.name)}
            >
              {t('friends.share.markRead')}
            </button>
          )}
        </div>
      </div>
      <button
        type="button"
        className="icon-btn"
        onClick={() => setOptions(true)}
      >
        <Icon name="more" label={t('friends.share.options', {title})} />
      </button>
      <Sheet
        open={options}
        title={t('friends.share.optionsTitle')}
        onClose={() => setOptions(false)}
      >
        <ul className="list">
          <li>
            <button
              type="button"
              className="list-row"
              onClick={() => {
                setOptions(false);
                remove.mutate(share.name, {
                  onSuccess: () => snackbar(t('friends.share.removed')),
                });
              }}
            >
              <Icon name="close" />
              <span className="list-row__body">
                {t('friends.share.remove')}
              </span>
            </button>
          </li>
          <li>
            <button
              type="button"
              className="list-row"
              onClick={() => {
                setOptions(false);
                onReport(share);
              }}
            >
              <Icon name="flag" />
              <span className="list-row__body">
                {t('friends.report.action')}
              </span>
            </button>
          </li>
          <li>
            <button
              type="button"
              className="list-row"
              onClick={() => {
                setOptions(false);
                block.mutate(share.sender.user, {
                  onSuccess: () =>
                    snackbar(t('friends.blocked', {name: sender})),
                });
              }}
            >
              <Icon name="block" />
              <span className="list-row__body">
                {t('friends.block', {name: sender})}
              </span>
            </button>
          </li>
        </ul>
      </Sheet>
    </li>
  );
}

function Inbox({onReport}: {onReport: (share: Share) => void}) {
  const {t} = useI18n();
  const inbox = useInbox(true);
  const markAll = useMarkInboxRead();
  const shares = inbox.data?.shares ?? [];

  if (inbox.isPending) return <SkeletonRows count={3} />;
  if (shares.length === 0)
    return (
      <EmptyState
        title={t('friends.inbox.empty.title')}
        body={t('friends.inbox.empty.body')}
      />
    );
  return (
    <section className="section" aria-labelledby="inbox-title">
      <div className="section__header">
        <h2 id="inbox-title">{t('friends.inbox.title')}</h2>
        {(inbox.data?.unreadCount ?? 0) > 0 && (
          <button
            type="button"
            className="btn btn--text btn--compact"
            onClick={() => markAll.mutate()}
          >
            {t('friends.inbox.markAll')}
          </button>
        )}
      </div>
      <ul className="list share-list">
        {shares.map(share => (
          <ShareCard key={share.name} share={share} onReport={onReport} />
        ))}
      </ul>
    </section>
  );
}

function InviteCard() {
  const {t} = useI18n();
  const snackbar = useSnackbar();
  const create = useCreateInvite();
  const invites = useFriendInvites(true);
  const revoke = useDeleteInvite();
  const navigate = useNavigate();
  const [code, setCode] = useState('');
  const created = create.data;
  const link = created ? `${location.origin}/friends/join/${created.code}` : '';
  const tooMany =
    create.error instanceof ApiError &&
    create.error.reason === 'TOO_MANY_INVITES';

  async function copy() {
    try {
      await navigator.clipboard.writeText(link);
      snackbar(t('friends.invite.copied'));
    } catch {
      snackbar(t('friends.invite.copyFailed'));
    }
  }

  async function shareLink() {
    try {
      await navigator.share({title: t('friends.invite.shareTitle'), url: link});
    } catch {
      // Dismissed or unsupported: the code and Copy are still on screen.
    }
  }

  function join(event: FormEvent) {
    event.preventDefault();
    const value = code.trim();
    if (value) void navigate(`/friends/join/${encodeURIComponent(value)}`);
  }

  const open = invites.data?.friendInvites ?? [];
  return (
    <section className="invite-card stack" aria-labelledby="invite-title">
      <div className="stack" style={{gap: 'var(--space-2)'}}>
        <h2 id="invite-title">{t('friends.invite.title')}</h2>
        <p className="muted">{t('friends.invite.body')}</p>
      </div>
      {created ? (
        <div className="stack invite-card__code">
          <p className="invite-code">
            <span className="visually-hidden">
              {t('friends.invite.codeLabel')}:{' '}
            </span>
            {created.code}
          </p>
          <p className="muted">
            {t('friends.invite.expires', {
              when: new Date(created.expireTime).toLocaleDateString(),
            })}
          </p>
          <div className="row">
            <button
              type="button"
              className="btn btn--filled"
              onClick={() => void copy()}
            >
              <Icon name="link" />
              {t('friends.invite.copy')}
            </button>
            {'share' in navigator && (
              <button
                type="button"
                className="btn btn--tonal"
                onClick={() => void shareLink()}
              >
                <Icon name="share" />
                {t('friends.invite.share')}
              </button>
            )}
          </div>
        </div>
      ) : (
        <button
          type="button"
          className="btn btn--accent"
          style={{alignSelf: 'flex-start'}}
          onClick={() => create.mutate()}
          disabled={create.isPending}
        >
          <Icon name="add" />
          {t('friends.invite.action')}
        </button>
      )}
      {tooMany && (
        <p className="banner" role="alert">
          {t('friends.invite.tooMany')}
        </p>
      )}
      {open.length > 0 && (
        <details className="invite-card__open">
          <summary>{t('friends.invite.open', {count: open.length})}</summary>
          <ul className="list">
            {open.map(invite => (
              <li key={invite.name} className="list-row">
                <span className="list-row__body">
                  <span className="list-row__title">
                    {t('friends.invite.openRow', {
                      when: new Date(invite.expireTime).toLocaleDateString(),
                    })}
                  </span>
                </span>
                <button
                  type="button"
                  className="btn btn--text btn--compact"
                  onClick={() => revoke.mutate(invite.name)}
                >
                  {t('friends.invite.revoke')}
                </button>
              </li>
            ))}
          </ul>
        </details>
      )}
      <form className="row" style={{flexWrap: 'nowrap'}} onSubmit={join}>
        <label className="visually-hidden" htmlFor="invite-code">
          {t('friends.join.label')}
        </label>
        <span className="field" style={{flex: 1}}>
          <input
            id="invite-code"
            autoComplete="off"
            spellCheck={false}
            placeholder={t('friends.join.placeholder')}
            value={code}
            onChange={event => setCode(event.target.value)}
          />
        </span>
        <button
          type="submit"
          className="btn btn--tonal"
          disabled={!code.trim()}
        >
          {t('friends.join.action')}
        </button>
      </form>
    </section>
  );
}

function FriendsList({
  onReport,
}: {
  onReport: (user: string, name: string) => void;
}) {
  const {t} = useI18n();
  const snackbar = useSnackbar();
  const friends = useFriends(true);
  const remove = useDeleteFriend();
  const block = useBlockUser();
  const blocked = useBlockedUsers(true);
  const unblock = useUnblockUser();
  const [menuFor, setMenuFor] = useState<{user: string; name: string} | null>(
    null,
  );
  const list = friends.data?.friends ?? [];
  const blockedList = blocked.data?.blockedUsers ?? [];

  return (
    <>
      <section className="section" aria-labelledby="friends-title">
        <div className="section__header">
          <h2 id="friends-title">{t('friends.list.title')}</h2>
          {list.length > 0 && <span className="badge">{list.length}</span>}
        </div>
        {friends.isPending && <SkeletonRows count={3} />}
        {friends.isSuccess && list.length === 0 && (
          <p className="muted">{t('friends.list.empty')}</p>
        )}
        <ul className="friend-grid">
          {list.map(friend => (
            <li key={friend.name} className="friend-tile">
              <Cover name={friend.person.displayName} round />
              <span className="friend-tile__name">
                <bdi>{friend.person.displayName}</bdi>
              </span>
              <span className="friend-tile__since">
                {t('friends.list.since', {
                  when: new Date(friend.createTime).toLocaleDateString(),
                })}
              </span>
              <button
                type="button"
                className="icon-btn friend-tile__more"
                onClick={() =>
                  setMenuFor({
                    user: friend.person.user,
                    name: friend.person.displayName,
                  })
                }
              >
                <Icon
                  name="more"
                  label={t('friends.list.options', {
                    name: friend.person.displayName,
                  })}
                />
              </button>
            </li>
          ))}
        </ul>
      </section>

      {blockedList.length > 0 && (
        <section className="section" aria-labelledby="blocked-title">
          <h2 id="blocked-title">{t('friends.blockedList.title')}</h2>
          <p className="muted">{t('friends.blockedList.body')}</p>
          <ul className="list">
            {blockedList.map(b => (
              <li key={b.name} className="list-row">
                <span className="list-row__body">
                  <span className="list-row__title">
                    <bdi>{b.person.displayName || t('friends.someone')}</bdi>
                  </span>
                </span>
                <button
                  type="button"
                  className="btn btn--text btn--compact"
                  onClick={() => unblock.mutate(b.person.user)}
                >
                  {t('friends.unblock')}
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}

      <Sheet
        open={menuFor !== null}
        title={menuFor?.name ?? ''}
        onClose={() => setMenuFor(null)}
      >
        {menuFor && (
          <ul className="list">
            <li>
              <button
                type="button"
                className="list-row"
                onClick={() => {
                  remove.mutate(menuFor.user, {
                    onSuccess: () =>
                      snackbar(t('friends.removed', {name: menuFor.name})),
                  });
                  setMenuFor(null);
                }}
              >
                <Icon name="close" />
                <span className="list-row__body">
                  {t('friends.remove', {name: menuFor.name})}
                </span>
              </button>
            </li>
            <li>
              <button
                type="button"
                className="list-row"
                onClick={() => {
                  block.mutate(menuFor.user, {
                    onSuccess: () =>
                      snackbar(t('friends.blocked', {name: menuFor.name})),
                  });
                  setMenuFor(null);
                }}
              >
                <Icon name="block" />
                <span className="list-row__body">
                  {t('friends.block', {name: menuFor.name})}
                </span>
              </button>
            </li>
            <li>
              <button
                type="button"
                className="list-row"
                onClick={() => {
                  onReport(menuFor.user, menuFor.name);
                  setMenuFor(null);
                }}
              >
                <Icon name="flag" />
                <span className="list-row__body">
                  {t('friends.report.action')}
                </span>
              </button>
            </li>
          </ul>
        )}
      </Sheet>
    </>
  );
}

export default function FriendsScreen() {
  const {t} = useI18n();
  const auth = useAuth();
  const flags = useConfigFlags();
  const signedIn = auth.status === 'signedIn';
  const profile = useSocialProfile(signedIn && flags.friends !== false);
  const inbox = useInbox(signedIn && flags.friends !== false);
  const [tab, setTab] = useState<'inbox' | 'friends'>('inbox');
  const [reportTarget, setReportTarget] = useState<{
    share?: Share;
    user?: string;
    name: string;
  } | null>(null);
  usePageTitle(t('friends.title'));
  const unread = inbox.data?.unreadCount ?? 0;

  return (
    <div className="stack product-screen">
      <section className="product-hero stack">
        <p className="product-hero__label">{t('nav.friends')}</p>
        <h1>{t('friends.title')}</h1>
        <p className="muted">{t('friends.lead')}</p>
      </section>

      {flags.friends === false ? (
        <p className="muted">{t('friends.off')}</p>
      ) : !signedIn ? (
        <EmptyState
          title={t('friends.signedOut')}
          action={
            <button
              type="button"
              className="btn btn--filled"
              onClick={() => void auth.signIn()}
              disabled={auth.status !== 'signedOut'}
            >
              {t('shell.signIn')}
            </button>
          }
        />
      ) : profile.isPending ? (
        <SkeletonRows count={3} />
      ) : !profile.data?.displayName ? (
        <NameCard />
      ) : (
        <>
          <p className="muted">
            {t('friends.youAppearAs', {name: profile.data.displayName})}
          </p>
          <div className="tabs" role="tablist" aria-label={t('friends.title')}>
            <button
              type="button"
              role="tab"
              id="tab-inbox"
              aria-controls="panel-inbox"
              aria-selected={tab === 'inbox'}
              className="tab"
              onClick={() => setTab('inbox')}
            >
              <Icon name="inbox" />
              {t('friends.tab.inbox')}
              {unread > 0 && (
                <span className="badge badge--accent">{unread}</span>
              )}
            </button>
            <button
              type="button"
              role="tab"
              id="tab-friends"
              aria-controls="panel-friends"
              aria-selected={tab === 'friends'}
              className="tab"
              onClick={() => setTab('friends')}
            >
              <Icon name="people" />
              {t('friends.tab.friends')}
            </button>
          </div>
          <div
            role="tabpanel"
            id={`panel-${tab}`}
            aria-labelledby={`tab-${tab}`}
            className="stack"
            style={{gap: 'var(--space-6)'}}
          >
            {tab === 'inbox' ? (
              <Inbox
                onReport={share =>
                  setReportTarget({share, name: share.sender.displayName})
                }
              />
            ) : (
              <>
                <InviteCard />
                <FriendsList
                  onReport={(user, name) => setReportTarget({user, name})}
                />
              </>
            )}
          </div>
        </>
      )}
      <ReportSheet
        target={reportTarget}
        onClose={() => setReportTarget(null)}
      />
    </div>
  );
}
