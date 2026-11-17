/**
 * Around you: what a campus and a city are listening to, from listeners who opt in.
 *
 * Joined communities open straight to their chart; anyone (signed out too) can
 * look around with the picker or a shared link (`?c=<community>`). Charts stay
 * locked until enough members have listening data, and say how many more.
 */
import {useState} from 'react';
import {Link, useSearchParams} from 'react-router';

import {
  communityId,
  useCommunity,
  useCommunityChart,
  useMyCommunities,
  useUpdateMyCommunities,
  type Community,
  type CommunityKind,
  type MembershipField,
} from '../api/community';
import {useConfigFlags} from '../app/flags';
import {usePageTitle} from '../app/Shell';
import {useAuth} from '../auth/AuthProvider';
import {ChartView, useShareCommunity} from '../community/ChartView';
import {CommunityPicker} from '../community/CommunityPicker';
import {cleanSlug, placeLabel} from '../community/format';
import {Icon} from '../components/Icon';
import {Cover} from '../components/Shelf';
import {useSnackbar} from '../components/Snackbar';
import {EmptyState, ErrorState, SkeletonRows} from '../components/States';
import {useI18n} from '../i18n/i18n';

const KINDS: CommunityKind[] = ['CAMPUS', 'CITY'];
const FIELD: Record<CommunityKind, MembershipField> = {
  CAMPUS: 'campus',
  CITY: 'city',
};

function Privacy() {
  const {t} = useI18n();
  return (
    <details className="more">
      <summary>{t('around.privacy.summary')}</summary>
      <div className="more__body">
        <p>{t('around.privacy.shared')}</p>
        <p>{t('around.privacy.thresholds', {min: 10, artistMin: 3})}</p>
        <p>{t('around.privacy.leave')}</p>
        <p className="muted">{t('around.pick.source')}</p>
      </div>
    </details>
  );
}

function CommunityHeader({
  community,
  joined,
  hasListeningData,
  onChange,
}: {
  community: Community;
  joined: boolean;
  hasListeningData: boolean | undefined;
  onChange: () => void;
}) {
  const {t} = useI18n();
  const auth = useAuth();
  const snackbar = useSnackbar();
  const update = useUpdateMyCommunities();
  const share = useShareCommunity();
  const field = FIELD[community.kind];
  const signedIn = auth.status === 'signedIn';

  function join() {
    if (!signedIn) {
      void auth.signIn();
      return;
    }
    update.mutate(
      {field, value: community.name},
      {
        onSuccess: () =>
          snackbar(t('around.join.done', {name: community.shortName})),
        onError: () => snackbar(t('state.error.title')),
      },
    );
  }

  function leave() {
    update.mutate(
      {field, value: ''},
      {
        onSuccess: () =>
          snackbar(t('around.leave.done', {name: community.shortName})),
      },
    );
  }

  return (
    <section className="community-head" aria-labelledby="community-name">
      <Cover name={community.displayName} />
      <div className="community-head__text">
        <p className="strapline">
          {joined ? t(`around.yours.${community.kind}`) : t('around.preview')}
        </p>
        <h2 id="community-name">
          <bdi>{community.displayName}</bdi>
        </h2>
        {community.synthetic && (
          <p className="banner">{t('around.demo.notice')}</p>
        )}
        <p className="muted">
          <bdi>{placeLabel(community)}</bdi>
          {community.sourceUrl && (
            <>
              {' · '}
              <a href={community.sourceUrl} target="_blank" rel="noreferrer">
                {t('around.source')}
              </a>
            </>
          )}
        </p>
      </div>
      <div className="row community-head__actions">
        {joined ? (
          <>
            <span className="joined-mark">
              <Icon name="check" />
              {t('around.joined')}
            </span>
            <button
              type="button"
              className="btn btn--outlined"
              disabled={update.isPending}
              aria-label={t('around.leaveNamed', {name: community.shortName})}
              onClick={leave}
            >
              {t('around.leave')}
            </button>
          </>
        ) : (
          <button
            type="button"
            className="btn btn--filled"
            disabled={update.isPending || auth.status === 'signingIn'}
            onClick={join}
          >
            <Icon name="add" />
            {signedIn ? t('around.join') : t('around.join.signIn')}
          </button>
        )}
        <button
          type="button"
          className="btn btn--tonal"
          onClick={() => void share(community.name, community.shortName)}
        >
          <Icon name="share" />
          {t('around.share')}
        </button>
        <button type="button" className="btn btn--text" onClick={onChange}>
          {t(`around.change.${community.kind}`)}
        </button>
      </div>
      {joined && hasListeningData === false && (
        <p className="banner community-head__nodata">
          <Icon name="info" />
          <span>{t('around.join.noData')}</span>
          <Link className="btn btn--text btn--compact" to="/library">
            {t('around.connect')}
          </Link>
        </p>
      )}
    </section>
  );
}

function CommunityChartSection({id}: {id: string}) {
  const chart = useCommunityChart(id);
  if (chart.isPending) return <SkeletonRows count={6} />;
  if (chart.isError)
    return (
      <ErrorState error={chart.error} onRetry={() => void chart.refetch()} />
    );
  return <ChartView chart={chart.data} />;
}

export default function AroundYouScreen() {
  const {t} = useI18n();
  const auth = useAuth();
  const flags = useConfigFlags();
  const [params, setParams] = useSearchParams();
  const [picking, setPicking] = useState(false);
  usePageTitle(t('nav.aroundYou'));

  const signedIn = auth.status === 'signedIn';
  const enabled = flags.community !== false;
  const linked = cleanSlug(params.get('c'));
  const shared = useCommunity(enabled ? linked : undefined);
  const mine = useMyCommunities(signedIn && enabled);
  const kind: CommunityKind =
    shared.data?.kind ?? (params.get('kind') === 'CITY' ? 'CITY' : 'CAMPUS');
  const membership = kind === 'CAMPUS' ? mine.data?.campus : mine.data?.city;
  const current = shared.data ?? membership?.community;
  const showPicker = picking || (!current && !(linked && shared.isPending));

  function choose(nextKind: CommunityKind) {
    setPicking(false);
    setParams(nextKind === 'CAMPUS' ? {} : {kind: nextKind});
  }

  function open(community: Community) {
    setPicking(false);
    setParams({c: communityId(community.name)});
  }

  if (!enabled) {
    return (
      <div className="stack">
        <h1>{t('nav.aroundYou')}</h1>
        <EmptyState title={t('state.unavailable.title')} />
      </div>
    );
  }

  return (
    <div className="around-you stack">
      <header className="page-header">
        <p className="strapline">{t('nav.aroundYou')}</p>
        <h1>{t('around.title')}</h1>
        <p className="lead">{t('around.lead')}</p>
      </header>

      <div className="tabs" role="tablist" aria-label={t('around.tabs')}>
        {KINDS.map(option => (
          <button
            key={option}
            type="button"
            role="tab"
            className="tab"
            aria-selected={option === kind}
            onClick={() => choose(option)}
          >
            <Icon name={option === 'CAMPUS' ? 'people' : 'place'} />
            {t(`around.tab.${option}`)}
          </button>
        ))}
      </div>

      <div
        role="tabpanel"
        aria-label={t(`around.tab.${kind}`)}
        className="stack"
      >
        {shared.isError && linked && (
          <p className="banner banner--error" role="alert">
            {t('state.notFound.title')}
          </p>
        )}
        {current && !showPicker && (
          <>
            <CommunityHeader
              community={current}
              joined={membership?.community.name === current.name}
              hasListeningData={mine.data?.hasListeningData}
              onChange={() => setPicking(true)}
            />
            <CommunityChartSection id={communityId(current.name)} />
          </>
        )}
        {showPicker && (
          <section className="section" aria-labelledby="pick-title">
            <h2 id="pick-title">{t(`around.pick.${kind}`)}</h2>
            <CommunityPicker kind={kind} onPick={open} />
          </section>
        )}
        <Privacy />
      </div>
    </div>
  );
}
