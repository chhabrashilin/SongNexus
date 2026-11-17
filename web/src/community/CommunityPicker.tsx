/** Search over the curated campus or city list; picking one opens its chart. */
import {useDeferredValue, useId, useState} from 'react';

import {
  useCommunities,
  type Community,
  type CommunityKind,
} from '../api/community';
import {Icon} from '../components/Icon';
import {Cover} from '../components/Shelf';
import {ErrorState, SkeletonRows} from '../components/States';
import {useI18n} from '../i18n/i18n';

import {placeLabel} from './format';

export function CommunityPicker({
  kind,
  onPick,
  exclude,
  label,
}: {
  kind: CommunityKind;
  onPick: (community: Community) => void;
  /** A community not to offer (the one being compared against). */
  exclude?: string;
  label?: string;
}) {
  const {t} = useI18n();
  const id = useId();
  const [query, setQuery] = useState('');
  const [country, setCountry] = useState('');
  const [demo, setDemo] = useState(false);
  const deferred = useDeferredValue(query.trim());
  const results = useCommunities(
    deferred,
    kind,
    country.length === 2 ? country : '',
    demo,
  );
  const items = (results.data?.communities ?? []).filter(
    c => c.name !== exclude,
  );
  const searchLabel = label ?? t(`around.search.${kind}`);

  return (
    <div className="community-picker">
      <div className="row">
        <label className="field">
          {t('around.country')}
          <input
            value={country}
            maxLength={2}
            placeholder="US"
            onChange={e =>
              setCountry(e.target.value.toUpperCase().replace(/[^A-Z]/g, ''))
            }
          />
        </label>
        {kind === 'CAMPUS' && (
          <label className="row">
            <input
              type="checkbox"
              checked={demo}
              onChange={e => setDemo(e.target.checked)}
            />
            {t('around.demo.only')}
          </label>
        )}
      </div>
      {demo && <p className="banner">{t('around.demo.notice')}</p>}
      <label className="field community-picker__field" htmlFor={`${id}-q`}>
        <Icon name="search" />
        <input
          id={`${id}-q`}
          type="search"
          value={query}
          placeholder={searchLabel}
          aria-label={searchLabel}
          aria-controls={`${id}-results`}
          autoComplete="off"
          enterKeyHint="search"
          onChange={event => setQuery(event.target.value)}
        />
      </label>
      <p className="visually-hidden" role="status">
        {results.isSuccess && t('around.pick.results', {count: items.length})}
      </p>
      {results.isError ? (
        <ErrorState
          error={results.error}
          onRetry={() => void results.refetch()}
        />
      ) : results.isPending ? (
        <SkeletonRows count={4} />
      ) : items.length === 0 ? (
        <p className="muted">{t('around.pick.empty', {query: deferred})}</p>
      ) : (
        <ul className="list" id={`${id}-results`}>
          {items.map(community => (
            <li key={community.name}>
              <button
                type="button"
                className="list-row"
                onClick={() => onPick(community)}
              >
                <Cover name={community.displayName} />
                <span className="list-row__body">
                  <span className="list-row__title">
                    <bdi>{community.displayName}</bdi>
                  </span>
                  <span className="list-row__subtitle">
                    <bdi>{placeLabel(community)}</bdi>
                    {community.synthetic && <> · {t('around.demo.label')}</>}
                  </span>
                </span>
                <Icon name="chevron" />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
