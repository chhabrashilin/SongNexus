/** "Your communities" on the You page: the campus and city you joined, with leave. */
import {Link} from 'react-router';

import {
  communityId,
  useMyCommunities,
  useUpdateMyCommunities,
  type MembershipField,
} from '../api/community';
import {useConfigFlags} from '../app/flags';
import {Icon} from '../components/Icon';
import {useSnackbar} from '../components/Snackbar';
import {useI18n} from '../i18n/i18n';

import {DemoBadge, plainName} from './CommunityPicker';
import {placeLabel} from './format';
import {CommunityMark} from './CommunityMark';

const FIELDS: MembershipField[] = ['campus', 'city'];

export function YourCommunities() {
  const {t} = useI18n();
  const flags = useConfigFlags();
  const snackbar = useSnackbar();
  const enabled = flags.community !== false;
  const mine = useMyCommunities(enabled);
  const update = useUpdateMyCommunities();
  if (!enabled) return null;

  const rows = FIELDS.flatMap(field => {
    const membership = mine.data?.[field];
    return membership ? [{field, community: membership.community}] : [];
  });

  return (
    <div className="settings-group__body">
      <p className="muted">{t('around.you.body')}</p>
      {mine.isPending ? (
        <span className="skeleton settings-skel" />
      ) : rows.length === 0 ? (
        <p className="quiet-note">
          <Icon name="school" />
          <span>{t('around.you.none')}</span>
        </p>
      ) : (
        <ul className="mini-cards">
          {rows.map(({field, community}) => (
            <li key={field} className="mini-card">
              <Link
                className="mini-card__link"
                to={`/around-you?c=${communityId(community.name)}`}
              >
                <CommunityMark community={community} allowWide={false} />
                <span className="mini-card__text">
                  <span className="mini-card__title">
                    <bdi>{plainName(community)}</bdi>
                  </span>
                  <span className="mini-card__sub">
                    {t(`around.yours.${community.kind}`)} ·{' '}
                    <bdi>{placeLabel(community)}</bdi>
                  </span>
                </span>
                {community.synthetic && <DemoBadge />}
              </Link>
              <button
                type="button"
                className="btn btn--text btn--compact"
                disabled={update.isPending}
                aria-label={t('around.leaveNamed', {name: community.shortName})}
                onClick={() =>
                  update.mutate(
                    {field, value: ''},
                    {
                      onSuccess: () =>
                        snackbar(
                          t('around.leave.done', {name: community.shortName}),
                        ),
                    },
                  )
                }
              >
                {t('around.leave')}
              </button>
            </li>
          ))}
        </ul>
      )}
      <Link className="btn btn--tonal settings-group__cta" to="/around-you">
        <Icon name="place" />
        {t('around.you.open')}
      </Link>
    </div>
  );
}
