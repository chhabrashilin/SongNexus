/**
 * Around you: what a campus and a city are listening to, from listeners who opt in.
 *
 * Joined communities open straight to their chart; anyone (signed out too) can
 * look around with the finder or a shared link (`?c=<community>`). Charts stay
 * locked until enough members have listening data, and say how many more.
 */
import {useRef, useState, type CSSProperties} from 'react';
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
  type UserCommunities,
} from '../api/community';
import {useAmbient} from '../app/ambient';
import {useConfigFlags} from '../app/flags';
import {usePageTitle} from '../app/Shell';
import {useAuth} from '../auth/AuthProvider';
import {ChartView, useShareCommunity} from '../community/ChartView';
import {
  CardSkeletons,
  CommunityCard,
  CommunityPicker,
  DemoBadge,
  plainName,
} from '../community/CommunityPicker';
import {cleanSlug, placeLabel} from '../community/format';
import {hueOf} from '../components/ArtistRow';
import {Icon} from '../components/Icon';
import {Sheet} from '../components/Sheet';
import {Cover} from '../components/Shelf';
import {useSnackbar} from '../components/Snackbar';
import {ErrorState} from '../components/States';
import {useI18n} from '../i18n/i18n';
import {Block, Hero, PromiseLine, RadarArt} from '../social/Hero';

const KINDS: CommunityKind[] = ['CAMPUS', 'CITY'];
const FIELD: Record<CommunityKind, MembershipField> = {
  CAMPUS: 'campus',
  CITY: 'city',
};
const MIN_MEMBERS = 10;
const MIN_ARTIST_LISTENERS = 3;

function PrivacyDetails() {
  const {t} = useI18n();
  return (
    <details className="more around__privacy">
      <summary>{t('around.privacy.summary')}</summary>
      <div className="more__body">
        <p>{t('around.privacy.shared')}</p>
        <p>
          {t('around.privacy.thresholds', {
            min: MIN_MEMBERS,
            artistMin: MIN_ARTIST_LISTENERS,
          })}
        </p>
        <p>{t('around.privacy.leave')}</p>
        <p>{t('around.pick.source')}</p>
        <p>
          <Link to="/privacy">{t('around.privacy.more')}</Link>
        </p>
      </div>
    </details>
  );
}

function KindSwitch({
  kind,
  onChange,
}: {
  kind: CommunityKind;
  onChange: (kind: CommunityKind) => void;
}) {
  const {t} = useI18n();
  return (
    <div className="segmented" role="tablist" aria-label={t('around.tabs')}>
      {KINDS.map(option => (
        <button
          key={option}
          type="button"
          role="tab"
          className="segmented__option"
          aria-selected={option === kind}
          onClick={() => onChange(option)}
        >
          <Icon name={option === 'CAMPUS' ? 'school' : 'city'} />
          {t(`around.tab.${option}`)}
        </button>
      ))}
    </div>
  );
}

/** Join or leave, each behind a short confirmation that says what it means. */
function Membership({
  community,
  joined,
  current,
}: {
  community: Community;
  joined: boolean;
  /** The community of this kind the listener belongs to now, if another. */
  current: Community | undefined;
}) {
  const {t} = useI18n();
  const auth = useAuth();
  const snackbar = useSnackbar();
  const update = useUpdateMyCommunities();
  const [confirm, setConfirm] = useState<'join' | 'leave' | null>(null);
  const field = FIELD[community.kind];
  const signedIn = auth.status === 'signedIn';
  const name = community.shortName;

  function run(action: 'join' | 'leave') {
    setConfirm(null);
    update.mutate(
      {field, value: action === 'join' ? community.name : ''},
      {
        onSuccess: () =>
          snackbar(
            action === 'join'
              ? current
                ? t('around.join.switched', {name})
                : t('around.join.done', {name})
              : t('around.leave.done', {name}),
          ),
        onError: () => snackbar(t('state.error.title')),
      },
    );
  }

  return (
    <>
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
            aria-label={t('around.leaveNamed', {name})}
            onClick={() => setConfirm('leave')}
          >
            {t('around.leave')}
          </button>
        </>
      ) : (
        <button
          type="button"
          className="btn btn--filled"
          disabled={update.isPending || auth.status === 'signingIn'}
          onClick={() => (signedIn ? setConfirm('join') : void auth.signIn())}
        >
          <Icon name="add" />
          {signedIn ? t('around.joinNamed', {name}) : t('around.join.signIn')}
        </button>
      )}
      <Sheet
        variant="dialog"
        open={confirm !== null}
        title={
          confirm === 'leave'
            ? t('around.leave.title', {name})
            : t('around.join.title', {name})
        }
        onClose={() => setConfirm(null)}
        actions={
          <>
            <button
              type="button"
              className="btn btn--text"
              onClick={() => setConfirm(null)}
            >
              {t('action.cancel')}
            </button>
            <button
              type="button"
              className={
                confirm === 'leave' ? 'btn btn--danger' : 'btn btn--filled'
              }
              onClick={() => confirm && run(confirm)}
            >
              {confirm === 'leave' ? t('around.leave') : t('around.join')}
            </button>
          </>
        }
      >
        {confirm === 'leave' ? (
          <p>{t('around.leave.body', {name})}</p>
        ) : (
          <div className="stack join-confirm">
            <p>{t('around.privacy.shared')}</p>
            <p className="muted">
              {t('around.privacy.thresholds', {
                min: MIN_MEMBERS,
                artistMin: MIN_ARTIST_LISTENERS,
              })}
            </p>
            {current && (
              <p className="banner">
                <Icon name="info" />
                <span>
                  {t(`around.join.replaces.${community.kind}`, {
                    name: current.shortName,
                  })}
                </span>
              </p>
            )}
            {community.synthetic && (
              <p className="banner">
                <Icon name="info" />
                <span>{t('around.demo.notice')}</span>
              </p>
            )}
          </div>
        )}
      </Sheet>
    </>
  );
}

/** The community being shown: its own hero with membership and sharing. */
function CommunityHero({
  community,
  mine,
  onChange,
}: {
  community: Community;
  mine: UserCommunities | undefined;
  onChange: () => void;
}) {
  const {t} = useI18n();
  const share = useShareCommunity();
  const current = mine?.[FIELD[community.kind]]?.community;
  const joined = current?.name === community.name;
  const name = plainName(community);

  return (
    <Hero
      overline={
        joined
          ? t(`around.yours.${community.kind}`)
          : t(`around.overline.${community.kind}`)
      }
      icon={community.kind === 'CAMPUS' ? 'school' : 'city'}
      titleId="community-name"
      title={<bdi>{name}</bdi>}
      hue={community.shortName || name}
      body={
        <p className="community-hero__place">
          <Icon name="place" size={18} />
          <bdi>{placeLabel(community)}</bdi>
          {community.synthetic && <DemoBadge />}
          {community.sourceUrl && (
            <a
              href={community.sourceUrl}
              target="_blank"
              rel="noopener noreferrer"
            >
              {t('around.source')}
            </a>
          )}
        </p>
      }
      actions={
        <>
          <Membership
            community={community}
            joined={joined}
            current={joined ? undefined : current}
          />
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
        </>
      }
      footnote={<PromiseLine>{t('around.promise')}</PromiseLine>}
      art={
        <div className="community-art">
          <RadarArt names={[name, community.city, community.country]} />
          <span
            className="community-art__cover"
            style={
              {'--hue': hueOf(community.shortName || name)} as CSSProperties
            }
          >
            <Cover name={community.shortName || name} eager />
          </span>
        </div>
      }
    />
  );
}

function ChartSection({id}: {id: string}) {
  const {t} = useI18n();
  const chart = useCommunityChart(id);
  if (chart.isPending)
    return (
      <div className="chart-skeleton" role="status">
        <span className="visually-hidden">{t('state.loading')}</span>
        <span className="skeleton chart-skeleton__panel" />
        <span className="skeleton chart-skeleton__line" />
        <span className="skeleton chart-skeleton__line chart-skeleton__line--short" />
      </div>
    );
  if (chart.isError)
    return (
      <ErrorState error={chart.error} onRetry={() => void chart.refetch()} />
    );
  return <ChartView chart={chart.data} />;
}

/** Signed in: the campus and city you joined, one tap away. */
function Yours({
  mine,
  onOpen,
}: {
  mine: UserCommunities;
  onOpen: (community: Community) => void;
}) {
  const {t} = useI18n();
  const joined = [mine.campus, mine.city].flatMap(m => (m ? [m] : []));
  if (joined.length === 0) return null;
  return (
    <Block id="yours-title" title={t('around.you.title')}>
      <ul className="community-grid community-grid--yours">
        {joined.map(m => (
          <CommunityCard
            key={m.community.name}
            community={m.community}
            note={t(`around.yours.${m.community.kind}`)}
            onPick={onOpen}
          />
        ))}
      </ul>
      {!mine.hasListeningData && <NoDataNote />}
    </Block>
  );
}

function NoDataNote() {
  const {t} = useI18n();
  return (
    <p className="banner around__nodata">
      <Icon name="info" />
      <span>{t('around.join.noData')}</span>
      <Link className="btn btn--text btn--compact" to="/library">
        {t('around.connect')}
      </Link>
    </p>
  );
}

/** Three short promises, shown before anything is picked. */
function HowItWorks() {
  const {t} = useI18n();
  const steps = [
    {icon: 'school', title: 'around.how.join', body: 'around.how.join.body'},
    {icon: 'lock', title: 'around.how.unlock', body: 'around.how.unlock.body'},
    {icon: 'leaderboard', title: 'around.how.see', body: 'around.how.see.body'},
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
          <span className="how-step__title">
            {t(step.title, {min: MIN_MEMBERS})}
          </span>
          <span className="how-step__body">
            {t(step.body, {min: MIN_MEMBERS})}
          </span>
        </li>
      ))}
    </ol>
  );
}

export default function AroundYouScreen() {
  const {t} = useI18n();
  const auth = useAuth();
  const flags = useConfigFlags();
  const [params, setParams] = useSearchParams();
  const [picking, setPicking] = useState(false);
  const finder = useRef<HTMLDivElement>(null);
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
  const loadingLinked = Boolean(linked) && shared.isPending;
  const loadingMine = signedIn && mine.isPending && !linked;
  const showPicker = picking || (!current && !loadingLinked && !loadingMine);
  useAmbient(current && !showPicker ? current.shortName : null);

  function choose(nextKind: CommunityKind) {
    setPicking(true);
    setParams(nextKind === 'CAMPUS' ? {} : {kind: nextKind});
  }

  function open(community: Community) {
    setPicking(false);
    setParams({c: communityId(community.name)});
    window.scrollTo({top: 0});
  }

  function toFinder() {
    finder.current?.scrollIntoView({behavior: 'smooth', block: 'start'});
    finder.current?.querySelector('input')?.focus({preventScroll: true});
  }

  if (!enabled) {
    return (
      <div className="around">
        <Hero
          overline={t('nav.aroundYou')}
          icon="place"
          title={t('around.title')}
          body={<p>{t('around.off')}</p>}
          art={<RadarArt />}
        />
      </div>
    );
  }

  return (
    <div className="around">
      {current && !showPicker ? (
        <CommunityHero
          community={current}
          mine={mine.data}
          onChange={() => setPicking(true)}
        />
      ) : (
        <Hero
          overline={t('nav.aroundYou')}
          icon="place"
          title={t('around.title')}
          body={<p>{t('around.lead')}</p>}
          actions={
            <button
              type="button"
              className="btn btn--filled"
              onClick={toFinder}
            >
              <Icon name="search" />
              {t(`around.pick.${kind}`)}
            </button>
          }
          footnote={<PromiseLine>{t('around.promise')}</PromiseLine>}
          art={
            <RadarArt names={['UW', 'Madison', 'Austin', 'Toronto', 'Seoul']} />
          }
        />
      )}

      {shared.isError && linked && (
        <p className="banner banner--error" role="alert">
          <Icon name="info" />
          <span>{t('around.linkMissing')}</span>
        </p>
      )}

      {loadingLinked || loadingMine ? (
        <CardSkeletons count={3} />
      ) : current && !showPicker ? (
        <>
          {membership?.community.name === current.name &&
            mine.data?.hasListeningData === false && <NoDataNote />}
          <ChartSection id={communityId(current.name)} />
        </>
      ) : (
        <>
          {mine.data && <Yours mine={mine.data} onOpen={open} />}
          <div className="around__finder" ref={finder}>
            <Block
              id="pick-title"
              eyebrow={t('around.pick.eyebrow')}
              title={t(`around.pick.${kind}`)}
              action={
                current && (
                  <button
                    type="button"
                    className="btn btn--outlined btn--compact"
                    onClick={() => setPicking(false)}
                  >
                    {t('around.pick.back', {name: current.shortName})}
                  </button>
                )
              }
            >
              <KindSwitch kind={kind} onChange={choose} />
              <div role="tabpanel" aria-label={t(`around.tab.${kind}`)}>
                <CommunityPicker key={kind} kind={kind} onPick={open} />
              </div>
            </Block>
          </div>
          {!mine.data?.campus && !mine.data?.city && <HowItWorks />}
        </>
      )}

      <PrivacyDetails />
    </div>
  );
}
