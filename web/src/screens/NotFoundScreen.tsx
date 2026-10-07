import {Link} from 'react-router';

import {usePageTitle} from '../app/Shell';
import {EmptyState} from '../components/States';
import {useI18n} from '../i18n/i18n';

export function NotFoundScreen() {
  const {t} = useI18n();
  usePageTitle(t('state.notFound.title'));
  return (
    <EmptyState
      title={t('state.notFound.title')}
      body={t('state.notFound.body')}
      action={
        <Link className="btn btn--tonal" to="/">
          {t('action.goHome')}
        </Link>
      }
    />
  );
}
