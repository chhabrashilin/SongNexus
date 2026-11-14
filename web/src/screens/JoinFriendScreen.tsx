/** Accept a friend invite from a link (`/friends/join/:code`) or a typed code. */
import {Link, useNavigate, useParams} from 'react-router';

import {ApiError} from '../api/client';
import {
  useAcceptInvite,
  useInvitePreview,
  useSocialProfile,
} from '../api/social';
import {usePageTitle} from '../app/Shell';
import {useAuth} from '../auth/AuthProvider';
import {Icon} from '../components/Icon';
import {Cover} from '../components/Shelf';
import {useSnackbar} from '../components/Snackbar';
import {EmptyState, Spinner} from '../components/States';
import {useI18n} from '../i18n/i18n';

import {NameCard} from './FriendsScreen';

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

  let body;
  if (!signedIn) {
    body = (
      <EmptyState
        title={t('friends.join.signIn')}
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
    );
  } else if (preview.isPending || profile.isPending) {
    body = <Spinner />;
  } else if (preview.isError) {
    body = (
      <EmptyState
        title={t('friends.join.invalid.title')}
        body={t('friends.join.invalid.body')}
        action={
          <Link className="btn btn--tonal" to="/friends">
            {t('friends.title')}
          </Link>
        }
      />
    );
  } else {
    const inviter = preview.data.inviter.displayName;
    const needsName = !profile.data?.displayName;
    body = (
      <div className="join-card stack">
        <div className="join-card__people" aria-hidden="true">
          <Cover name={inviter} round />
          <span className="join-card__link">
            <Icon name="link" />
          </span>
          <Cover name={profile.data?.displayName || '?'} round />
        </div>
        <h2>{t('friends.join.from', {name: inviter})}</h2>
        <p className="muted">{t('friends.join.what')}</p>
        {preview.data.alreadyFriends ? (
          <Link className="btn btn--tonal" to="/friends">
            {t('friends.join.already')}
          </Link>
        ) : needsName ? (
          <NameCard lead={t('friends.join.nameFirst', {name: inviter})} />
        ) : (
          <div className="row" style={{justifyContent: 'center'}}>
            <button
              type="button"
              className="btn btn--accent"
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
      </div>
    );
  }

  return (
    <div className="stack product-screen">
      <section className="product-hero stack">
        <p className="product-hero__label">{t('nav.friends')}</p>
        <h1>{t('friends.join.title')}</h1>
      </section>
      {body}
    </div>
  );
}
