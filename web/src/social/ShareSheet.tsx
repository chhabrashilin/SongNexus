/**
 * Share with a friend (R2-7): an artist, a song, a comparison or a path, with
 * an optional note (140 characters). Friends only; the server moderates notes
 * and limits how often anyone can send.
 */
import {useState, type FormEvent} from 'react';
import {Link} from 'react-router';

import {ApiError, idOf} from '../api/client';
import {useCreateShare, useFriends, type ShareKind} from '../api/social';
import {useConfigFlags} from '../app/flags';
import {useAuth} from '../auth/AuthProvider';
import {Icon} from '../components/Icon';
import {Sheet} from '../components/Sheet';
import {Cover} from '../components/Shelf';
import {useSnackbar} from '../components/Snackbar';
import {SkeletonRows} from '../components/States';
import {useI18n} from '../i18n/i18n';
import type {MessageId} from '../i18n/messages';

export const NOTE_MAX = 140;

/** Where a share opens in the app. */
export function sharePath(kind: ShareKind, subjects: string[]): string {
  const [a = '', b = ''] = subjects.map(idOf);
  switch (kind) {
    case 'ARTIST':
      return `/artist/${a}`;
    case 'RECORDING':
      return `/song/${a}`;
    case 'ARTIST_COMPARISON':
      return `/compare?a=${a}&b=${b}`;
    case 'RECORDING_COMPARISON':
      return `/compare/songs?a=${a}&b=${b}`;
    case 'PATH':
      return `/six-degrees?from=${a}&to=${b}`;
  }
}

const SEND_ERRORS: Record<string, MessageId> = {
  TEXT_HAS_LINK: 'share.error.link',
  TEXT_HAS_HIDDEN_CHARACTERS: 'share.error.text',
  TEXT_REJECTED: 'share.error.text',
  SHARE_LIMIT: 'share.error.limit',
  DISPLAY_NAME_REQUIRED: 'share.error.name',
  FRIEND_NOT_FOUND: 'share.error.friend',
};

function ShareForm({
  kind,
  subjects,
  title,
  onDone,
}: {
  kind: ShareKind;
  subjects: string[];
  title: string;
  onDone: () => void;
}) {
  const {t} = useI18n();
  const snackbar = useSnackbar();
  const friends = useFriends(true);
  const send = useCreateShare();
  const [recipient, setRecipient] = useState<string | null>(null);
  const [note, setNote] = useState('');
  const list = friends.data?.friends ?? [];

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!recipient) return;
    send.mutate(
      {recipient, kind, subjects, note: note.trim()},
      {
        onSuccess: share => {
          snackbar(t('share.sent', {name: share.recipient.displayName}));
          setNote('');
          onDone();
        },
      },
    );
  }

  const errorReason =
    send.error instanceof ApiError ? send.error.reason : undefined;

  if (friends.isPending) return <SkeletonRows count={3} />;
  if (list.length === 0)
    return (
      <div className="stack">
        <p className="muted">{t('share.noFriends')}</p>
        <Link className="btn btn--filled" to="/friends" onClick={onDone}>
          <Icon name="add" />
          {t('friends.invite.action')}
        </Link>
      </div>
    );

  return (
    <form className="stack" onSubmit={submit}>
      <p className="share-subject">
        <Icon name={kind === 'PATH' ? 'route' : 'share'} />
        <span>{title}</span>
      </p>
      <fieldset className="friend-picker">
        <legend className="label">{t('share.to')}</legend>
        {list.map(friend => (
          <label key={friend.person.user} className="friend-picker__option">
            <input
              type="radio"
              name="recipient"
              value={friend.person.user}
              checked={recipient === friend.person.user}
              onChange={() => setRecipient(friend.person.user)}
            />
            <Cover name={friend.person.displayName} round />
            <span>{friend.person.displayName}</span>
          </label>
        ))}
      </fieldset>
      <label className="stack" style={{gap: 'var(--space-1)'}}>
        <span className="label">{t('share.note')}</span>
        <textarea
          className="textarea"
          rows={3}
          maxLength={NOTE_MAX}
          value={note}
          placeholder={t('share.notePlaceholder')}
          onChange={event => setNote(event.target.value)}
        />
        <span className="muted counter" aria-live="polite">
          {t('share.noteCount', {count: NOTE_MAX - note.length})}
        </span>
      </label>
      {send.isError && (
        <p className="banner banner--error" role="alert">
          {t(SEND_ERRORS[errorReason ?? ''] ?? 'share.error.generic')}
        </p>
      )}
      <div className="dialog__actions">
        <button type="button" className="btn btn--text" onClick={onDone}>
          {t('action.cancel')}
        </button>
        <button
          type="submit"
          className="btn btn--accent"
          disabled={!recipient || send.isPending}
        >
          <Icon name="send" />
          {t('share.send')}
        </button>
      </div>
    </form>
  );
}

/** "Share with a friend" button plus its sheet. Hidden when friends are switched off. */
export function ShareButton({
  kind,
  subjects,
  title,
}: {
  kind: ShareKind;
  subjects: string[];
  title: string;
}) {
  const {t} = useI18n();
  const auth = useAuth();
  const flags = useConfigFlags();
  const snackbar = useSnackbar();
  const [open, setOpen] = useState(false);
  if (flags.friends === false || subjects.some(s => !s)) return null;

  return (
    <>
      <button
        type="button"
        className="btn btn--tonal"
        onClick={() =>
          auth.status === 'signedIn'
            ? setOpen(true)
            : snackbar(t('share.signIn'))
        }
      >
        <Icon name="send" />
        {t('share.button')}
      </button>
      <Sheet
        open={open}
        title={t('share.title')}
        onClose={() => setOpen(false)}
      >
        {open && (
          <ShareForm
            kind={kind}
            subjects={subjects}
            title={title}
            onDone={() => setOpen(false)}
          />
        )}
      </Sheet>
    </>
  );
}
