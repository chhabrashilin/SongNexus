/**
 * Catalog search as an ARIA 1.2 combobox (M5-02): typing shows suggestions,
 * arrow keys move, Enter picks, Escape closes. Works in any script.
 */
import {useDeferredValue, useEffect, useId, useRef, useState} from 'react';

import {idOf, type Schemas} from '../api/client';
import {useSearch} from '../api/queries';
import {useI18n} from '../i18n/i18n';

import {Avatar} from './ArtistRow';
import {Icon} from './Icon';

type Result = Schemas['SearchResult'];

interface Props {
  label?: string;
  placeholder?: string;
  types?: Schemas['EntityType'][];
  onPick: (result: Result) => void;
  autoFocus?: boolean;
  initialQuery?: string;
  /** Clear the box after a pick (search bar) or keep the picked name (artist pickers). */
  clearOnPick?: boolean;
}

/** Where a result leads. R1 has artist and song pages; releases are not searchable yet. */
export function resultPath(
  result: Pick<Result, 'name' | 'entityType'>,
): string {
  const id = idOf(result.name);
  return result.entityType === 'RECORDING' ? `/song/${id}` : `/artist/${id}`;
}

export function SearchBox({
  label,
  placeholder,
  types = ['ARTIST', 'RECORDING'],
  onPick,
  autoFocus = false,
  initialQuery = '',
  clearOnPick = true,
}: Props) {
  const {t} = useI18n();
  const [query, setQuery] = useState(initialQuery);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const deferred = useDeferredValue(query);
  const search = useSearch(deferred, types);
  const listId = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const results = deferred.trim() ? (search.data?.results ?? []) : [];

  useEffect(() => setActive(-1), [deferred]);

  function pick(result: Result) {
    onPick(result);
    setQuery(clearOnPick ? '' : result.displayName);
    setOpen(false);
  }

  const showPopup =
    open &&
    deferred.trim().length > 0 &&
    (results.length > 0 || search.isFetched);

  return (
    <div className="combobox">
      <label className="field">
        <Icon name="search" />
        <span className="visually-hidden">{label ?? t('search.label')}</span>
        <input
          ref={inputRef}
          type="search"
          role="combobox"
          aria-expanded={showPopup}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={
            active >= 0 ? `${listId}-${active}` : undefined
          }
          autoComplete="off"
          spellCheck={false}
          maxLength={120}
          autoFocus={autoFocus}
          placeholder={placeholder ?? t('search.placeholder')}
          value={query}
          onChange={event => {
            setQuery(event.target.value);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onBlur={() => window.setTimeout(() => setOpen(false), 150)}
          onKeyDown={event => {
            if (event.key === 'ArrowDown') {
              event.preventDefault();
              setOpen(true);
              setActive(i => Math.min(i + 1, results.length - 1));
            } else if (event.key === 'ArrowUp') {
              event.preventDefault();
              setActive(i => Math.max(i - 1, 0));
            } else if (event.key === 'Enter') {
              const chosen = results[active >= 0 ? active : 0];
              if (chosen) {
                event.preventDefault();
                pick(chosen);
              }
            } else if (event.key === 'Escape') {
              setOpen(false);
            }
          }}
        />
      </label>
      <ul
        id={listId}
        role="listbox"
        className="list combobox__popup"
        hidden={!showPopup}
      >
        {results.map((result, index) => (
          <li
            key={result.name}
            id={`${listId}-${index}`}
            role="option"
            aria-selected={index === active}
            className="list-row combobox__option"
            // Pointer down, not click: it fires before the input's blur closes the popup.
            onPointerDown={event => {
              event.preventDefault();
              pick(result);
            }}
          >
            {result.entityType === 'ARTIST' ? (
              <Avatar name={result.displayName} />
            ) : (
              <span className="avatar" aria-hidden="true">
                <Icon
                  name={result.entityType === 'RECORDING' ? 'note' : 'album'}
                />
              </span>
            )}
            <span className="list-row__body">
              <span className="list-row__title">
                <bdi>{result.displayName}</bdi>
              </span>
              <span className="list-row__subtitle">
                {[
                  t(`search.type.${result.entityType}`),
                  result.subtitle,
                  result.blocked ? t('search.blocked') : '',
                ]
                  .filter(Boolean)
                  .join(' · ')}
              </span>
            </span>
          </li>
        ))}
        {results.length === 0 && search.isFetched && (
          <li className="list-row" aria-disabled="true">
            <span className="muted">
              {t('search.noResults', {query: deferred.trim()})}
            </span>
          </li>
        )}
      </ul>
      <span className="visually-hidden" aria-live="polite">
        {showPopup ? t('search.results', {count: results.length}) : ''}
      </span>
    </div>
  );
}
