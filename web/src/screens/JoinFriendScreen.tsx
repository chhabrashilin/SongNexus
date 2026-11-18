/**
 * Accept a friend invite from a link (`/friends/join/:code`) or a typed code:
 * one welcoming card with both of you, what being friends means, and accept.
 */
import type {CSSProperties, ReactNode} from 'react';
import {Link, useNavigate, useParams} from 'react-router';

import {ApiError} from '../api/client';
import {
  useAcceptInvite,
  useInvitePreview,
  useSocialProfile,
} from '../api/social';
import {useAmbient} from '../app/ambient';
import {usePageTitle} from '../app/Shell';
import {useAuth} from '../auth/AuthProvider';
import {hueOf} from '../components/ArtistRow';
import {Icon} from '../components/Icon';
import {Cover} from '../components/Shelf';
import {useSnackbar} from '../components/Snackbar';
import {useI18n} from '../i18n/i18n';

import {NameCard} from './FriendsScreen';

function Perks() {
  const {t} = useI18n();
  return (
    <ul className="join__perks">
      <li>
        <Icon name="send" />
        {t('friends.join.perk.share')}
      </li>
      <li>
        <Icon name="route" />
        {t('friends.join.perk.paths')}
      </li>
      <li>
        <Icon name="shield" />
        {t('friends.join.perk.private')}
      </li>
    </ul>
  );
}

function JoinCard({
  inviter,
  you,
  eyebrow,
  title,
  body,
  children,
}: {
  inviter: string;
  you: string;
  eyebrow: string;
  title?: string;
  body?: string;
  children?: ReactNode;
}) {
  const {t} = useI18n();
  return (
    <section
      className="join"
      aria-labelledby="join-title"
      style={{'--hue': hueOf(inviter || 'friends')} as CSSProperties}
    >
      <div className="join__people" aria-hidden="true">
        <Cover
          name={inviter || '?'}
          icon={inviter ? undefined : 'person'}
          round
        />
        <span className="join__bridge">
          <Icon name="link" />
        </span>
        <Cover name={you || '?'} icon={you ? undefined : 'person'} round />
      </div>
      <p className="join__eyebrow">{eyebrow}</p>
      <h1 id="join-title" className="join__title">
        {t('friends.join.title')}
      </h1>
      {title && (
        <p className="join__headline">
          <bdi>{title}</bdi>
        </p>
      )}
      {body && <p className="join__body">{body}</p>}
      {children}
    </section>
  );
}

export default function JoinFriendScreen() {
  const {t} = useI18n();
  const {code = ''} = useParams();
  const auth = useAuth();
  const navigate = useNavigate();
  const snackbar = useSnackbar();
  const signedIn = auth.status === 'signedIn';
  const profile = useSocialProfile(signedIn);
  const preview = useInvitePreview(code, signedIn);
  const accept = useAcceptInvite();
  usePageTitle(t('friends.join.title'));
  useAmbient(preview.data?.inviter.displayName ?? null);

  if (!signedIn)
    return (
      <div className="join-page">
        <JoinCard
          inviter=""
          you=""
          eyebrow={t('friends.join.eyebrow')}
          body={t('friends.join.signIn')}
        >
          <div className="join__actions">
            <button
              type="button"
              className="btn btn--filled"
              onClick={() => void auth.signIn()}
              disabled={auth.status !== 'signedOut'}
            >
              <Icon name="person" />
              {t('shell.signIn')}
            </button>
          </div>
          <Perks />
        </JoinCard>
      </div>
    );

  if (preview.isPending || profile.isPending)
    return (
      <div className="join-page" role="status">
        <span className="visually-hidden">{t('state.loading')}</span>
        <span className="skeleton join-skel" />
      </div>
    );

  if (preview.isError)
    return (
      <div className="join-page">
        <JoinCard
          inviter=""
          you={profile.data?.displayName ?? ''}
          eyebrow={t('friends.join.invalid.title')}
          body={t('friends.join.invalid.body')}
        >
          <div className="join__actions">
            <Link className="btn btn--tonal" to="/friends">
              <Icon name="people" />
              {t('friends.title')}
            </Link>
          </div>
        </JoinCard>
      </div>
    );

  const inviter = preview.data.inviter.displayName;
  const you = profile.data?.displayName ?? '';
  return (
    <div className="join-page">
      <JoinCard
        inviter={inviter}
        you={you}
        eyebrow={t('friends.join.eyebrow')}
        title={t('friends.join.from', {name: inviter})}
        body={t('friends.join.what')}
      >
        {preview.data.alreadyFriends ? (
          <div className="join__actions">
            <Link className="btn btn--tonal" to="/friends">
              <Icon name="check" />
              {t('friends.join.already')}
            </Link>
          </div>
        ) : !you ? (
          <NameCard lead={t('friends.join.nameFirst', {name: inviter})} />
        ) : (
          <div className="join__actions">
            <button
              type="button"
              className="btn btn--filled"
              disabled={accept.isPending}
              onClick={() =>
                accept.mutate(code, {
                  onSuccess: () => {
                    snackbar(t('friends.join.done', {name: inviter}));
                    void navigate('/friends', {replace: true});
                  },
                })
              }
            >
              <Icon name="check" />
              {t('friends.join.accept')}
            </button>
            <Link className="btn btn--text" to="/">
              {t('friends.join.notNow')}
            </Link>
          </div>
        )}
        {accept.isError && (
          <p className="banner banner--error" role="alert">
            {accept.error instanceof ApiError &&
            accept.error.reason === 'TOO_MANY_FRIENDS'
              ? t('friends.join.tooMany')
              : t('friends.join.invalid.body')}
          </p>
        )}
        <Perks />
      </JoinCard>
    </div>
  );
}
