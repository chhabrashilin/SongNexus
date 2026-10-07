/** Loading, empty and error states. Every limitation gets an honest, specific message (plan §8). */
import type {ReactNode} from 'react';

import {ApiError} from '../api/client';
import {useI18n} from '../i18n/i18n';

export function Spinner() {
  const {t} = useI18n();
  return (
    <div className="state" role="status">
      <span className="visually-hidden">{t('state.loading')}</span>
      <div
        className="skeleton"
        style={{inlineSize: '60%', blockSize: 16}}
        aria-hidden="true"
      />
      <div
        className="skeleton"
        style={{inlineSize: '40%', blockSize: 16}}
        aria-hidden="true"
      />
    </div>
  );
}

export function SkeletonRows({count = 5}: {count?: number}) {
  const {t} = useI18n();
  return (
    <div role="status" aria-live="polite">
      <span className="visually-hidden">{t('state.loading')}</span>
      {Array.from({length: count}, (_, i) => (
        <div key={i} className="list-row" aria-hidden="true">
          <div
            className="skeleton"
            style={{inlineSize: 40, blockSize: 40, borderRadius: '50%'}}
          />
          <div className="list-row__body">
            <div
              className="skeleton"
              style={{inlineSize: `${50 + ((i * 13) % 35)}%`, blockSize: 14}}
            />
          </div>
        </div>
      ))}
    </div>
  );
}

export function EmptyState({
  title,
  body,
  action,
}: {
  title: string;
  body?: string;
  action?: ReactNode;
}) {
  return (
    <div className="state">
      <p className="state__title">{title}</p>
      {body && <p className="state__body">{body}</p>}
      {action}
    </div>
  );
}

/** Explains a failed request in plain language, with a retry when retrying can help. */
export function ErrorState({
  error,
  onRetry,
}: {
  error: unknown;
  onRetry?: () => void;
}) {
  const {t} = useI18n();
  let title = t('state.error.title');
  let body = t('state.error.body');
  if (error instanceof ApiError) {
    if (error.status === 'NOT_FOUND') {
      title = t('state.notFound.title');
      body = t('state.notFound.body');
    } else if (
      error.status === 'UNAVAILABLE' &&
      error.reason === 'CATALOG_UNAVAILABLE'
    ) {
      title = t('state.unavailable.title');
      body = t('state.unavailable.body');
    } else if (error.status === 'RESOURCE_EXHAUSTED') {
      body = t('state.rateLimited', {seconds: error.retryAfterSeconds ?? 5});
    }
  }
  return (
    <div className="state" role="alert">
      <p className="state__title">{title}</p>
      <p className="state__body">{body}</p>
      {onRetry && (
        <button type="button" className="btn btn--tonal" onClick={onRetry}>
          {t('action.retry')}
        </button>
      )}
    </div>
  );
}
