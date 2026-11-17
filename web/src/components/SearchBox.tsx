/**
 * Catalog search as an ARIA 1.2 combobox (M5-02): typing shows suggestions,
 * arrow keys move, Enter picks, Escape closes. Works in any script.
 *
 * In the main search bar it also takes questions (Ask, ADR 0008): when the text
 * reads like a question, the first option is "Ask SongNexus: …", and Enter on it
 * (or the sparkle button) shows an answer from our data in a panel under the
 * bar. Focus stays in the input throughout; Escape closes the panel.
 */
import {useDeferredValue, useEffect, useId, useRef, useState} from 'react';

import {readsLikeQuestion, useAsk, answerText} from '../api/ask';
import {idOf, type Schemas} from '../api/client';
import {useConfig, useSearch} from '../api/queries';
import {useI18n} from '../i18n/i18n';

import {Avatar} from './ArtistRow';
import {AskAnswer, useListFormat, type AskState} from './AskAnswer';
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
  /**
   * Offer "Ask SongNexus" for questions. Default: on for the general catalog
   * search (no custom label), off for pickers that choose one artist or song.
   */
  ask?: boolean;
}

/** Where a result leads. R1 has artist and song pages; releases are not searchable yet. */
export function resultPath(
  result: Pick<Result, 'name' | 'entityType'>,
): string {
  const id = idOf(result.name);
  return result.entityType === 'RECORDING' ? `/song/${id}` : `/artist/${id}`;
}

type Option = {kind: 'ask'} | {kind: 'result'; result: Result};

export function SearchBox({
  label,
  placeholder,
  types = ['ARTIST', 'RECORDING'],
  onPick,
  autoFocus = false,
  initialQuery = '',
  clearOnPick = true,
  ask,
}: Props) {
  const {t} = useI18n();
  const formatList = useListFormat();
  const config = useConfig();
  const askEnabled =
    (ask ?? label === undefined) && config.data?.flags.ask === true;
  const [query, setQuery] = useState(initialQuery);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const [answer, setAnswer] = useState<AskState | null>(null);
  const deferred = useDeferredValue(query);
  const search = useSearch(deferred, types);
  const asking = useAsk();
  const baseId = useId();
  const listId = `${baseId}-list`;
  const inputId = `${baseId}-input`;
  const panelId = `${baseId}-answer`;
  const inputRef = useRef<HTMLInputElement>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const askToken = useRef(0);
  const results = deferred.trim() ? (search.data?.results ?? []) : [];
  const offerAsk = askEnabled && readsLikeQuestion(deferred);
  const options: Option[] = [
    ...(offerAsk ? [{kind: 'ask'} as const] : []),
    ...results.map(result => ({kind: 'result', result}) as const),
  ];

  useEffect(() => setActive(-1), [deferred]);

  // A click anywhere else closes the answer, as it does the suggestions.
  useEffect(() => {
    if (!answer) return;
    const onPointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setAnswer(null);
    };
    document.addEventListener('pointerdown', onPointerDown);
    return () => document.removeEventListener('pointerdown', onPointerDown);
  }, [answer]);

  function pick(result: Result) {
    onPick(result);
    setQuery(clearOnPick ? '' : result.displayName);
    setOpen(false);
    setAnswer(null);
  }

  function askQuestion(text: string, choices: string[] = []) {
    const question = text.trim().slice(0, 120);
    if (!question) return;
    const token = ++askToken.current;
    setQuery(question);
    setOpen(false);
    setActive(-1);
    setAnswer({status: 'loading', query: question});
    asking.mutate(
      {query: question, choices},
      {
        // Only the latest question's answer is shown.
        onSuccess: response =>
          token === askToken.current &&
          setAnswer({status: 'done', query: question, response}),
        onError: error =>
          token === askToken.current &&
          setAnswer({status: 'error', query: question, error}),
      },
    );
  }

  function closeAnswer() {
    askToken.current++;
    setAnswer(null);
  }

  function choose(option: Option | undefined): boolean {
    if (!option) return false;
    if (option.kind === 'ask') askQuestion(query);
    else pick(option.result);
    return true;
  }

  const showPopup =
    open &&
    !answer &&
    deferred.trim().length > 0 &&
    (options.length > 0 || search.isFetched);

  const announcement = answer
    ? answer.status === 'loading'
      ? t('ask.loading')
      : answer.status === 'error'
        ? t('ask.error')
        : answerText(answer.response.answer, formatList, t)
    : showPopup
      ? t('search.results', {count: results.length})
      : '';

  return (
    <div className="combobox" ref={rootRef}>
      <div className="field">
        <Icon name="search" />
        <label htmlFor={inputId} className="visually-hidden">
          {label ?? t('search.label')}
        </label>
        <input
          id={inputId}
          ref={inputRef}
          type="search"
          role="combobox"
          aria-expanded={showPopup}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={
            showPopup && active >= 0 ? `${listId}-${active}` : undefined
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
            if (answer) closeAnswer();
          }}
          onFocus={() => setOpen(true)}
          onBlur={() => window.setTimeout(() => setOpen(false), 150)}
          onKeyDown={event => {
            if (event.key === 'ArrowDown') {
              event.preventDefault();
              setOpen(true);
              setActive(i => Math.min(i + 1, options.length - 1));
            } else if (event.key === 'ArrowUp') {
              event.preventDefault();
              setActive(i => Math.max(i - 1, 0));
            } else if (event.key === 'Enter') {
              // Enter takes the active option, else the first one (Ask, when offered).
              const chosen =
                options[active >= 0 ? active : 0] ??
                (askEnabled && query.trim()
                  ? ({kind: 'ask'} as const)
                  : undefined);
              if (choose(chosen)) event.preventDefault();
            } else if (event.key === 'Escape') {
              if (answer) {
                event.preventDefault();
                closeAnswer();
              }
              setOpen(false);
            }
          }}
        />
        {askEnabled && query.trim() && (
          <button
            type="button"
            className="icon-btn search-ask"
            aria-label={t('ask.button')}
            title={t('ask.button')}
            // Pointer down, not click, so the input keeps focus.
            onPointerDown={event => {
              event.preventDefault();
              askQuestion(query);
              inputRef.current?.focus();
            }}
            onClick={event => {
              // Keyboard activation (pointer down already asked for mouse and touch).
              if (event.detail === 0) askQuestion(query);
            }}
          >
            <Icon name="spark" />
          </button>
        )}
      </div>
      <ul
        id={listId}
        role="listbox"
        aria-label={label ?? t('search.label')}
        className="list combobox__popup"
        hidden={!showPopup}
      >
        {options.map((option, index) =>
          option.kind === 'ask' ? (
            <li
              key="ask"
              id={`${listId}-${index}`}
              role="option"
              aria-selected={index === active}
              className="list-row combobox__option combobox__option--ask"
              onPointerDown={event => {
                event.preventDefault();
                askQuestion(query);
              }}
            >
              <span className="avatar avatar--ask" aria-hidden="true">
                <Icon name="spark" />
              </span>
              <span className="list-row__body">
                <span className="list-row__title">
                  {t('ask.option', {query: deferred.trim()})}
                </span>
              </span>
            </li>
          ) : (
            <li
              key={option.result.name}
              id={`${listId}-${index}`}
              role="option"
              aria-selected={index === active}
              className="list-row combobox__option"
              // Pointer down, not click: it fires before the input's blur closes the popup.
              onPointerDown={event => {
                event.preventDefault();
                pick(option.result);
              }}
            >
              {option.result.entityType === 'ARTIST' ? (
                <Avatar name={option.result.displayName} />
              ) : (
                <span className="avatar" aria-hidden="true">
                  <Icon
                    name={
                      option.result.entityType === 'RECORDING'
                        ? 'note'
                        : 'album'
                    }
                  />
                </span>
              )}
              <span className="list-row__body">
                <span className="list-row__title">
                  <bdi>{option.result.displayName}</bdi>
                </span>
                <span className="list-row__subtitle">
                  {[
                    t(`search.type.${option.result.entityType}`),
                    option.result.subtitle,
                    option.result.blocked ? t('search.blocked') : '',
                  ]
                    .filter(Boolean)
                    .join(' · ')}
                </span>
              </span>
            </li>
          ),
        )}
        {results.length === 0 && search.isFetched && !offerAsk && (
          <li className="list-row" aria-disabled="true">
            <span className="muted">
              {t('search.noResults', {query: deferred.trim()})}
            </span>
          </li>
        )}
      </ul>
      {answer && (
        <AskAnswer
          id={panelId}
          state={answer}
          onAsk={(text, choices) => {
            askQuestion(text, choices);
            inputRef.current?.focus();
          }}
          onClose={() => {
            closeAnswer();
            inputRef.current?.focus();
          }}
          onNavigate={closeAnswer}
        />
      )}
      <span className="visually-hidden" aria-live="polite">
        {announcement}
      </span>
    </div>
  );
}
