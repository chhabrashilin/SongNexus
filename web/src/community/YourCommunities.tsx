/** "Your communities" on the You page: the campus and city you joined, with one-tap leave. */
import {Link} from 'react-router';

import {
  communityId,
  useMyCommunities,
  useUpdateMyCommunities,
  type MembershipField,
} from '../api/community';
import {useConfigFlags} from '../app/flags';
import {Cover} from '../components/Shelf';
import {useSnackbar} from '../components/Snackbar';
import {SkeletonRows} from '../components/States';
import {useI18n} from '../i18n/i18n';

import {placeLabel} from './format';

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
    <section className="section" aria-labelledby="your-communities">
      <h2 id="your-communities">{t('around.you.title')}</h2>
      <p className="muted">{t('around.you.body')}</p>
      {mine.isPending ? (
        <SkeletonRows count={2} />
      ) : rows.length === 0 ? (
        <p className="muted">{t('around.you.none')}</p>
      ) : (
        <ul className="list">
          {rows.map(({field, community}) => (
            <li key={field} className="row" style={{flexWrap: 'nowrap'}}>
              <Link
                className="list-row"
                style={{flex: 1, minInlineSize: 0}}
                to={`/around-you?c=${communityId(community.name)}`}
              >
                <Cover name={community.displayName} />
                <span className="list-row__body">
                  <span className="list-row__title">
                    <bdi>{community.displayName}</bdi>
                  </span>
                  <span className="list-row__subtitle">
                    {t(`around.yours.${community.kind}`)} ·{' '}
                    <bdi>{placeLabel(community)}</bdi>
                  </span>
                </span>
              </Link>
              <button
                type="button"
                className="btn btn--text"
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
      <Link className="btn btn--tonal" to="/around-you">
        {t('around.you.open')}
      </Link>
    </section>
  );
}
