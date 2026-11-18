/**
 * Friends (R2-7): inviting is the hero (a link and a code, copy or share),
 * then what friends sent you as cards, your friends, how your music connects
 * to theirs (friend paths), and blocks, open invites and sharing tucked into
 * "Privacy and safety". Friends join only through an invite you send: there is
 * no search, no contact upload and no public directory.
 */
import {
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type FormEvent,
} from 'react';
import {Link, useNavigate} from 'react-router';

import {ApiError, idOf} from '../api/client';
import {useShareTopArtists} from '../api/personal';
import {useArtist} from '../api/queries';
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
  type Friend,
  type ReportReason,
  type Share,
} from '../api/social';
import {useAmbient} from '../app/ambient';
import {useConfigFlags} from '../app/flags';
import {usePageTitle} from '../app/Shell';
import {useAuth} from '../auth/AuthProvider';
import {Avatar, hueOf, imageOf} from '../components/ArtistRow';
import {Icon, type IconName} from '../components/Icon';
import {Sheet} from '../components/Sheet';
import {Cover} from '../components/Shelf';
import {useSnackbar} from '../components/Snackbar';
import {ErrorState} from '../components/States';
import {useI18n} from '../i18n/i18n';
import type {MessageId} from '../i18n/messages';
import {FriendPaths} from '../social/FriendPaths';
import {Block, Hero, PromiseLine} from '../social/Hero';
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

const KIND_ICON: Record<Share['kind'], IconName> = {
  ARTIST: 'person',
  RECORDING: 'note',
  ARTIST_COMPARISON: 'compare',
  RECORDING_COMPARISON: 'compare',
  PATH: 'route',
};

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
    <form className="stack name-card" onSubmit={submit}>
      <h2 className="name-card__title">{t('friends.name.title')}</h2>
      <p className="muted">{lead ?? t('friends.name.body')}</p>
      <div className="code-form">
        <label className="search-pill">
          <Icon name="person" />
          <span className="visually-hidden">{t('friends.name.label')}</span>
          <input
            id="display-name"
            maxLength={40}
            autoComplete="nickname"
            placeholder={t('friends.name.placeholder')}
            value={name}
            onChange={event => setName(event.target.value)}
          />
        </label>
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

interface ReportTarget {
  share?: Share;
  user?: string;
  name: string;
}

/** Report a share or a person; optionally block them in the same step. */
function ReportSheet({
  target,
  onClose,
}: {
  target: ReportTarget | null;
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
        <fieldset className="stack report-reasons">
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

/** The cover of something shared: the artist's photo when we have one. */
function SubjectCover({
  name,
  displayName,
}: {
  name: string;
  displayName: string;
}) {
  const isArtist = name.startsWith('artists/');
  const artist = useArtist(isArtist ? idOf(name) : undefined);
  return (
    <Cover
      name={displayName || name}
      image={imageOf(artist.data)}
      icon={isArtist ? undefined : 'note'}
      round={isArtist}
    />
  );
}

function ShareCard({
  share,
  index,
  onReport,
}: {
  share: Share;
  index: number;
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
    <li
      className="inbox-card"
      data-unread={!share.read || undefined}
      style={{'--hue': hueOf(title), '--i': index} as CSSProperties}
    >
      <div className="inbox-card__art" aria-hidden="true">
        {share.subjects.slice(0, 2).map((subject, i) => (
          <span key={subject.name} className="inbox-card__cover">
            {i > 0 && share.kind === 'PATH' && (
              <span className="inbox-card__arrow">
                <Icon name="route" size={18} />
              </span>
            )}
            <SubjectCover
              name={subject.name}
              displayName={subject.displayName}
            />
          </span>
        ))}
        <span className="inbox-card__kind">
          <Icon name={KIND_ICON[share.kind]} />
          {t(`share.kind.${share.kind}` as MessageId)}
        </span>
        {!share.read && (
          <span className="inbox-card__unread">{t('friends.share.new')}</span>
        )}
      </div>
      <div className="inbox-card__body">
        <p className="inbox-card__title">
          {!share.read && (
            <span className="visually-hidden">{t('friends.share.new')}: </span>
          )}
          <bdi>{title}</bdi>
        </p>
        <div className="inbox-card__note">
          <Avatar name={sender} />
          <div className="stack inbox-card__said">
            {share.note && (
              <p className="inbox-card__bubble">
                <bdi>{share.note}</bdi>
              </p>
            )}
            <p className="inbox-card__from">
              {t('friends.share.from', {
                name: sender,
                when: ago(t, share.createTime),
              })}
            </p>
          </div>
        </div>
        <div className="inbox-card__actions">
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
          <button
            type="button"
            className="icon-btn"
            onClick={() => setOptions(true)}
          >
            <Icon name="more" label={t('friends.share.options', {title})} />
          </button>
        </div>
      </div>
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
              <Icon name="trash" />
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

function CardSkeletons({count}: {count: number}) {
  const {t} = useI18n();
  return (
    <div className="skel-grid" role="status">
      <span className="visually-hidden">{t('state.loading')}</span>
      {Array.from({length: count}, (_, i) => (
        <span key={i} className="skeleton skel-card" aria-hidden="true" />
      ))}
    </div>
  );
}

function Inbox({onReport}: {onReport: (share: Share) => void}) {
  const {t} = useI18n();
  const inbox = useInbox(true);
  const markAll = useMarkInboxRead();
  const shares = inbox.data?.shares ?? [];
  const unread = inbox.data?.unreadCount ?? 0;

  return (
    <Block
      id="inbox-title"
      eyebrow={
        unread > 0
          ? t('friends.inbox.unread', {count: unread})
          : t('friends.inbox.eyebrow')
      }
      title={t('friends.inbox.title')}
      action={
        unread > 0 && (
          <button
            type="button"
            className="btn btn--outlined btn--compact"
            onClick={() => markAll.mutate()}
          >
            <Icon name="check" />
            {t('friends.inbox.markAll')}
          </button>
        )
      }
    >
      {inbox.isPending ? (
        <CardSkeletons count={3} />
      ) : inbox.isError ? (
        <ErrorState error={inbox.error} onRetry={() => void inbox.refetch()} />
      ) : shares.length === 0 ? (
        <div className="empty-card">
          <Icon name="inbox" size={32} />
          <p className="empty-card__title">{t('friends.inbox.empty.title')}</p>
          <p className="muted">{t('friends.inbox.empty.body')}</p>
        </div>
      ) : (
        <ul className="inbox-grid stagger">
          {shares.map((share, i) => (
            <ShareCard
              key={share.name}
              share={share}
              index={i}
              onReport={onReport}
            />
          ))}
        </ul>
      )}
    </Block>
  );
}

/** Copies text and shows the result on the button itself for a moment. */
function useCopied(): [boolean, (text: string) => Promise<void>] {
  const {t} = useI18n();
  const snackbar = useSnackbar();
  const [done, setDone] = useState(false);
  const timer = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(timer.current), []);
  async function copy(text: string) {
    try {
      await navigator.clipboard.writeText(text);
      setDone(true);
      snackbar(t('friends.invite.copied'));
      window.clearTimeout(timer.current);
      timer.current = window.setTimeout(() => setDone(false), 2400);
    } catch {
      snackbar(t('friends.invite.copyFailed'));
    }
  }
  return [done, copy];
}

/** The invite you just made: the code large, the link, copy and share. */
function InviteMade({code, expireTime}: {code: string; expireTime: string}) {
  const {t, locale} = useI18n();
  const [copiedLink, copyLink] = useCopied();
  const [copiedCode, copyCode] = useCopied();
  const link = `${location.origin}/friends/join/${code}`;
  const canShare = typeof navigator.share === 'function';

  async function shareLink() {
    try {
      await navigator.share({
        title: t('friends.invite.shareTitle'),
        text: t('friends.invite.shareText', {code}),
        url: link,
      });
    } catch {
      // Dismissed or unsupported: the code and Copy are still on screen.
    }
  }

  return (
    <div className="invite-made" role="status">
      <p className="invite-pass__label">{t('friends.invite.codeLabel')}</p>
      <p className="invite-made__code">{code}</p>
      <label className="invite-made__link">
        <span className="visually-hidden">{t('friends.invite.linkLabel')}</span>
        <Icon name="link" />
        <input
          readOnly
          value={link}
          onFocus={event => event.currentTarget.select()}
        />
      </label>
      <div className="invite-made__actions">
        <button
          type="button"
          className="btn btn--filled"
          data-done={copiedLink || undefined}
          onClick={() => void copyLink(link)}
        >
          <Icon name={copiedLink ? 'check' : 'copy'} />
          {copiedLink
            ? t('friends.invite.copiedShort')
            : t('friends.invite.copy')}
        </button>
        <button
          type="button"
          className="btn btn--tonal"
          data-done={copiedCode || undefined}
          onClick={() => void copyCode(code)}
        >
          <Icon name={copiedCode ? 'check' : 'copy'} />
          {copiedCode
            ? t('friends.invite.copiedShort')
            : t('friends.invite.copyCode')}
        </button>
        {canShare && (
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
      <p className="invite-made__expires">
        {t('friends.invite.expires', {
          when: new Date(expireTime).toLocaleDateString(locale),
        })}
      </p>
    </div>
  );
}

/** "Have a code?" */
function CodeForm() {
  const {t} = useI18n();
  const navigate = useNavigate();
  const [code, setCode] = useState('');
  function join(event: FormEvent) {
    event.preventDefault();
    const value = code.trim();
    if (value) void navigate(`/friends/join/${encodeURIComponent(value)}`);
  }
  return (
    <form className="code-form" onSubmit={join}>
      <label className="search-pill">
        <Icon name="link" />
        <span className="visually-hidden">{t('friends.join.label')}</span>
        <input
          id="invite-code"
          autoComplete="off"
          spellCheck={false}
          placeholder={t('friends.join.placeholder')}
          value={code}
          onChange={event => setCode(event.target.value)}
        />
      </label>
      <button type="submit" className="btn btn--tonal" disabled={!code.trim()}>
        {t('friends.join.action')}
      </button>
    </form>
  );
}

/** The hero's art: a pass with your friends' faces and room for one more. */
function InvitePass({friends}: {friends: Friend[]}) {
  const {t} = useI18n();
  return (
    <div className="invite-pass">
      <p className="invite-pass__label">{t('friends.invite.pass')}</p>
      <p className="invite-pass__code" aria-hidden="true">
        ••••• – •••••
      </p>
      <span className="invite-pass__people">
        {friends.slice(0, 4).map(friend => (
          <Cover key={friend.name} name={friend.person.displayName} round />
        ))}
        <span className="invite-pass__plus">
          <Icon name="add" />
        </span>
      </span>
    </div>
  );
}

function FriendsBlock({
  selected,
  onSelect,
  onInvite,
  onReport,
}: {
  selected: string | undefined;
  onSelect: (friend: Friend) => void;
  onInvite: () => void;
  onReport: (user: string, name: string) => void;
}) {
  const {t, locale} = useI18n();
  const snackbar = useSnackbar();
  const friends = useFriends(true);
  const remove = useDeleteFriend();
  const block = useBlockUser();
  const [menuFor, setMenuFor] = useState<{user: string; name: string} | null>(
    null,
  );
  const [confirmRemove, setConfirmRemove] = useState<{
    user: string;
    name: string;
  } | null>(null);
  const list = friends.data?.friends ?? [];

  return (
    <Block
      id="friends-title"
      eyebrow={
        list.length > 0
          ? t('friends.list.count', {count: list.length})
          : undefined
      }
      title={t('friends.list.title')}
    >
      {friends.isPending ? (
        <div className="friend-tiles" role="status">
          <span className="visually-hidden">{t('state.loading')}</span>
          {[0, 1, 2].map(i => (
            <span key={i} className="skeleton friend-card friend-card--skel" />
          ))}
        </div>
      ) : (
        <ul className="friend-tiles stagger">
          {list.map((friend, i) => (
            <li
              key={friend.name}
              className="friend-card"
              data-selected={selected === friend.person.user || undefined}
              style={{'--i': i} as CSSProperties}
            >
              <button
                type="button"
                className="friend-card__main"
                aria-pressed={selected === friend.person.user}
                onClick={() => onSelect(friend)}
              >
                <Cover name={friend.person.displayName} round />
                <span className="friend-card__name">
                  <bdi>{friend.person.displayName}</bdi>
                </span>
                <span className="friend-card__since">
                  {t('friends.list.since', {
                    when: new Date(friend.createTime).toLocaleDateString(
                      locale,
                    ),
                  })}
                </span>
                <span className="friend-card__cta">
                  <Icon name="route" size={16} />
                  {t('friends.list.paths')}
                </span>
              </button>
              <button
                type="button"
                className="icon-btn friend-card__more"
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
          <li className="friend-card friend-card--invite">
            <button
              type="button"
              className="friend-card__main"
              onClick={onInvite}
            >
              <span className="friend-card__plus">
                <Icon name="add" size={32} />
              </span>
              <span className="friend-card__name">
                {t('friends.list.invite')}
              </span>
              <span className="friend-card__since">
                {list.length === 0
                  ? t('friends.list.empty')
                  : t('friends.list.inviteBody')}
              </span>
            </button>
          </li>
        </ul>
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
                  setConfirmRemove(menuFor);
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
      <Sheet
        variant="dialog"
        open={confirmRemove !== null}
        title={t('friends.remove.title', {name: confirmRemove?.name ?? ''})}
        onClose={() => setConfirmRemove(null)}
        actions={
          <>
            <button
              type="button"
              className="btn btn--text"
              onClick={() => setConfirmRemove(null)}
            >
              {t('action.cancel')}
            </button>
            <button
              type="button"
              className="btn btn--danger"
              onClick={() => {
                const target = confirmRemove;
                setConfirmRemove(null);
                if (target)
                  remove.mutate(target.user, {
                    onSuccess: () =>
                      snackbar(t('friends.removed', {name: target.name})),
                  });
              }}
            >
              {t('friends.remove.confirm')}
            </button>
          </>
        }
      >
        <p>{t('friends.remove.body', {name: confirmRemove?.name ?? ''})}</p>
      </Sheet>
    </Block>
  );
}

/** How your music connects to one friend's, with a friend picker. */
function PathsBlock({
  friend,
  friends,
  onSelect,
}: {
  friend: Friend | undefined;
  friends: Friend[];
  onSelect: (friend: Friend) => void;
}) {
  const {t} = useI18n();
  if (!friend) return null;
  return (
    <Block
      id="paths-title"
      eyebrow={t('paths.eyebrow')}
      title={t('paths.title', {name: friend.person.displayName})}
      className="paths-block"
    >
      {friends.length > 1 && (
        <ul className="chips chips--scroll" aria-label={t('paths.pick')}>
          {friends.map(f => (
            <li key={f.name}>
              <button
                type="button"
                className="chip"
                aria-pressed={f.person.user === friend.person.user}
                onClick={() => onSelect(f)}
              >
                <bdi>{f.person.displayName}</bdi>
              </button>
            </li>
          ))}
        </ul>
      )}
      <FriendPaths
        key={friend.person.user}
        user={friend.person.user}
        name={friend.person.displayName}
      />
    </Block>
  );
}

/** Blocks, open invites and sharing: reachable, but out of the way. */
function Safety() {
  const {t, locale} = useI18n();
  const snackbar = useSnackbar();
  const profile = useSocialProfile(true);
  const shareTop = useShareTopArtists();
  const invites = useFriendInvites(true);
  const revoke = useDeleteInvite();
  const blocked = useBlockedUsers(true);
  const unblock = useUnblockUser();
  const open = invites.data?.friendInvites ?? [];
  const blockedList = blocked.data?.blockedUsers ?? [];
  const sharing = profile.data?.shareTopArtists ?? false;

  return (
    <details className="safety">
      <summary>
        <Icon name="shield" />
        <span className="stack safety__summary">
          <span>{t('friends.safety.title')}</span>
          <span className="safety__sub">
            {t('friends.safety.sub', {
              blocked: blockedList.length,
              invites: open.length,
            })}
          </span>
        </span>
      </summary>
      <div className="safety__body">
        <section
          className="stack safety__group"
          aria-labelledby="sharing-title"
        >
          <h3 id="sharing-title">{t('friends.sharing.title')}</h3>
          <label className="switch-row">
            <span className="stack switch-row__text">
              <span>{t('friends.sharing.label')}</span>
              <span className="muted">{t('friends.sharing.body')}</span>
            </span>
            <input
              type="checkbox"
              role="switch"
              className="switch"
              checked={sharing}
              disabled={!profile.data || shareTop.isPending}
              onChange={event =>
                shareTop.mutate(event.target.checked, {
                  onSuccess: data =>
                    snackbar(
                      data.shareTopArtists
                        ? t('paths.sharing.on')
                        : t('paths.sharing.off'),
                    ),
                })
              }
            />
          </label>
        </section>

        <section
          className="stack safety__group"
          aria-labelledby="invites-title"
        >
          <h3 id="invites-title">
            {t('friends.invite.open', {count: open.length})}
          </h3>
          {open.length === 0 ? (
            <p className="muted">{t('friends.invite.none')}</p>
          ) : (
            <ul className="list">
              {open.map(invite => (
                <li key={invite.name} className="list-row">
                  <Icon name="link" />
                  <span className="list-row__body">
                    <span className="list-row__title">
                      {t('friends.invite.openRow', {
                        when: new Date(invite.expireTime).toLocaleDateString(
                          locale,
                        ),
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
          )}
        </section>

        <section
          className="stack safety__group"
          aria-labelledby="blocked-title"
        >
          <h3 id="blocked-title">{t('friends.blockedList.title')}</h3>
          <p className="muted">{t('friends.blockedList.body')}</p>
          {blockedList.length === 0 ? (
            <p className="muted">{t('friends.blockedList.none')}</p>
          ) : (
            <ul className="list">
              {blockedList.map(b => (
                <li key={b.name} className="list-row">
                  <Icon name="block" />
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
          )}
        </section>
        <p className="muted">
          {t('friends.safety.report')}{' '}
          <Link to="/privacy">{t('friends.safety.privacy')}</Link>
        </p>
      </div>
    </details>
  );
}

/** Signed out or first run: what friends adds, in three steps. */
function HowFriendsWork() {
  const {t} = useI18n();
  const steps = [
    {
      icon: 'link',
      title: 'friends.how.invite',
      body: 'friends.how.invite.body',
    },
    {icon: 'send', title: 'friends.how.share', body: 'friends.how.share.body'},
    {icon: 'route', title: 'friends.how.paths', body: 'friends.how.paths.body'},
  ] as const;
  return (
    <ol className="how-steps">
      {steps.map((step, i) => (
        <li key={step.title} className="how-step">
          <span className="how-step__icon">
            <Icon name={step.icon} />
          </span>
          <span className="how-step__n" aria-hidden="true">
            {i + 1}
          </span>
          <span className="how-step__title">{t(step.title)}</span>
          <span className="how-step__body">{t(step.body)}</span>
        </li>
      ))}
    </ol>
  );
}

function SignedIn({name}: {name: string}) {
  const {t} = useI18n();
  const create = useCreateInvite();
  const friends = useFriends(true);
  const [picked, setPicked] = useState<string | undefined>(undefined);
  const [report, setReport] = useState<ReportTarget | null>(null);
  const hero = useRef<HTMLDivElement>(null);
  const paths = useRef<HTMLDivElement>(null);
  const list = friends.data?.friends ?? [];
  const selected =
    list.find(f => f.person.user === picked) ?? list[0] ?? undefined;
  const tooMany =
    create.error instanceof ApiError &&
    create.error.reason === 'TOO_MANY_INVITES';

  function invite() {
    hero.current?.scrollIntoView({behavior: 'smooth', block: 'start'});
    if (!create.data && !create.isPending) create.mutate();
  }

  function select(friend: Friend) {
    setPicked(friend.person.user);
    paths.current?.scrollIntoView({behavior: 'smooth', block: 'start'});
  }

  return (
    <>
      <div ref={hero} className="friends__hero">
        <Hero
          overline={t('friends.overline', {name})}
          icon="people"
          title={t('friends.title')}
          hue="friends"
          body={
            <>
              <p>{t('friends.lead')}</p>
              {create.data && (
                <InviteMade
                  code={create.data.code}
                  expireTime={create.data.expireTime}
                />
              )}
              {tooMany && (
                <p className="banner" role="alert">
                  <Icon name="info" />
                  <span>{t('friends.invite.tooMany')}</span>
                </p>
              )}
            </>
          }
          actions={
            !create.data && (
              <button
                type="button"
                className="btn btn--filled"
                onClick={() => create.mutate()}
                disabled={create.isPending}
              >
                <Icon name="link" />
                {t('friends.invite.action')}
              </button>
            )
          }
          footnote={
            <div className="stack friends__footnote">
              <p className="muted">{t('friends.invite.body')}</p>
              <CodeForm />
            </div>
          }
          art={<InvitePass friends={list} />}
        />
      </div>

      <Inbox
        onReport={share => setReport({share, name: share.sender.displayName})}
      />

      <FriendsBlock
        selected={selected?.person.user}
        onSelect={select}
        onInvite={invite}
        onReport={(user, n) => setReport({user, name: n})}
      />

      <div ref={paths} className="friends__paths">
        <PathsBlock friend={selected} friends={list} onSelect={select} />
      </div>

      <Safety />

      <ReportSheet target={report} onClose={() => setReport(null)} />
    </>
  );
}

export default function FriendsScreen() {
  const {t} = useI18n();
  const auth = useAuth();
  const flags = useConfigFlags();
  const enabled = flags.friends !== false;
  const signedIn = auth.status === 'signedIn';
  const profile = useSocialProfile(signedIn && enabled);
  usePageTitle(t('friends.title'));
  useAmbient(null);

  if (!enabled)
    return (
      <div className="friends">
        <Hero
          overline={t('nav.friends')}
          icon="people"
          title={t('friends.title')}
          hue="friends"
          body={<p>{t('friends.off')}</p>}
        />
      </div>
    );

  if (!signedIn)
    return (
      <div className="friends">
        <Hero
          overline={t('nav.friends')}
          icon="people"
          title={t('friends.title')}
          hue="friends"
          body={
            <>
              <p>{t('friends.lead')}</p>
              <p className="muted">{t('friends.signedOut')}</p>
            </>
          }
          actions={
            <button
              type="button"
              className="btn btn--filled"
              onClick={() => void auth.signIn()}
              disabled={auth.status !== 'signedOut'}
            >
              <Icon name="person" />
              {t('shell.signIn')}
            </button>
          }
          footnote={<PromiseLine>{t('friends.promise')}</PromiseLine>}
          art={<InvitePass friends={[]} />}
        />
        <HowFriendsWork />
      </div>
    );

  if (profile.isPending)
    return (
      <div className="friends" role="status">
        <span className="visually-hidden">{t('state.loading')}</span>
        <span className="skeleton p-hero-skel" />
        <CardSkeletons count={3} />
      </div>
    );

  if (profile.isError)
    return (
      <div className="friends">
        <Hero
          overline={t('nav.friends')}
          icon="people"
          title={t('friends.title')}
          hue="friends"
        />
        <ErrorState
          error={profile.error}
          onRetry={() => void profile.refetch()}
        />
      </div>
    );

  if (!profile.data.displayName)
    return (
      <div className="friends">
        <Hero
          overline={t('nav.friends')}
          icon="people"
          title={t('friends.title')}
          hue="friends"
          body={<p>{t('friends.lead')}</p>}
          footnote={<PromiseLine>{t('friends.promise')}</PromiseLine>}
          art={<InvitePass friends={[]} />}
        />
        <NameCard />
        <HowFriendsWork />
      </div>
    );

  return (
    <div className="friends">
      <SignedIn name={profile.data.displayName} />
    </div>
  );
}
