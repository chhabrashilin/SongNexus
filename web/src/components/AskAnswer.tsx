/**
 * The answer to a question asked in the search bar (ADR 0008): one line from
 * our data, the names it understood, up to three supporting rows, the page
 * with the full answer, and how the answer was made one tap away.
 */
import {useMemo} from 'react';
import {Link} from 'react-router';

import {
  ambiguousEntity,
  answerText,
  destinationLabel,
  EXAMPLES,
  needsExamples,
  yearLabel,
  type AskResponse,
  type AskRow,
} from '../api/ask';
import {ApiError, idOf} from '../api/client';
import {useI18n} from '../i18n/i18n';
import type {MessageId} from '../i18n/messages';

import {Avatar} from './ArtistRow';
import {evidenceText} from './evidence';
import {Icon} from './Icon';

const MAX_ROWS = 3;

export type AskState =
  | {status: 'loading'; query: string}
  | {status: 'error'; query: string; error: unknown}
  | {status: 'done'; query: string; response: AskResponse};

interface Props {
  state: AskState;
  id: string;
  /** Ask again: a new question, or the same one with a "Did you mean" pick. */
  onAsk: (query: string, choices?: string[]) => void;
  onClose: () => void;
  /** A link in the answer was followed. */
  onNavigate: () => void;
}

/** Formats a list of names for the viewer's language ("A, B and C"). */
export function useListFormat(): (items: string[]) => string {
  const {locale} = useI18n();
  return useMemo(() => {
    const format = new Intl.ListFormat(
      locale === 'ar-XB' ? 'ar' : locale === 'en-US' ? 'en-US' : 'en',
      {style: 'long', type: 'conjunction'},
    );
    return (items: string[]) => format.format(items);
  }, [locale]);
}

const ROLE_LABELS: Record<string, MessageId> = {
  producer: 'ask.row.role.producer',
  featured: 'ask.row.role.featured',
  primary: 'ask.row.role.primary',
};

function Row({
  row,
  nameOf,
  onNavigate,
}: {
  row: AskRow;
  nameOf: (name: string) => string;
  onNavigate: () => void;
}) {
  const {t} = useI18n();
  const evidence = row.evidence[0];
  const details = [
    evidence ? evidenceText(evidence, nameOf, t) : null,
    !evidence && row.role
      ? t(ROLE_LABELS[row.role] ?? 'ask.row.role.other')
      : null,
    row.count ? t('ask.row.count', {count: row.count}) : null,
    row.firstYear && row.lastYear && !evidence
      ? row.firstYear === row.lastYear
        ? String(row.firstYear)
        : `${row.firstYear}–${row.lastYear}`
      : null,
  ].filter(Boolean);
  if (row.artist) {
    return (
      <li>
        <Link
          className="list-row"
          to={`/artist/${idOf(row.artist.name)}`}
          onClick={onNavigate}
        >
          <Avatar name={row.artist.displayName} />
          <span className="list-row__body">
            <span className="list-row__title">
              <bdi>{row.artist.displayName}</bdi>
            </span>
            {details.length > 0 && (
              <span className="list-row__subtitle">{details.join(' · ')}</span>
            )}
          </span>
        </Link>
      </li>
    );
  }
  if (!row.recording) return null;
  return (
    <li>
      <Link
        className="list-row"
        to={`/song/${idOf(row.recording.name)}`}
        onClick={onNavigate}
      >
        <span className="avatar" aria-hidden="true">
          <Icon name="note" />
        </span>
        <span className="list-row__body">
          <span className="list-row__title">
            <bdi>{row.recording.displayName}</bdi>
          </span>
          <span className="list-row__subtitle">
            {[t('ask.row.song'), row.recording.subtitle]
              .filter(Boolean)
              .join(' · ')}
          </span>
        </span>
      </Link>
    </li>
  );
}

function Examples({onAsk}: {onAsk: (query: string) => void}) {
  const {t} = useI18n();
  return (
    <div className="ask__examples">
      <p className="ask__label">{t('ask.examples')}</p>
      <div className="chips">
        {EXAMPLES.map(id => (
          <button
            key={id}
            type="button"
            className="chip"
            onClick={() => onAsk(t(id))}
          >
            {t(id)}
          </button>
        ))}
      </div>
    </div>
  );
}

function Answer({
  response,
  query,
  onAsk,
  onNavigate,
}: {
  response: AskResponse;
  query: string;
  onAsk: Props['onAsk'];
  onNavigate: () => void;
}) {
  const {t} = useI18n();
  const formatList = useListFormat();
  const names = useMemo(
    () => new Map(response.artists.map(a => [a.name, a.displayName])),
    [response.artists],
  );
  const nameOf = (name: string) => names.get(name) ?? '';
  const ambiguous = ambiguousEntity(response);
  const interpretation = response.interpretation;
  const years = yearLabel(interpretation.startYear, interpretation.endYear, t);
  const matched = response.entities.filter(
    e => e.status === 'MATCHED' && e.match,
  );
  const chosen = matched.map(e => e.match!.name);
  return (
    <>
      <p className="ask__answer">
        {answerText(response.answer, formatList, t)}
      </p>
      {(matched.length > 0 || years || interpretation.genreDisplayName) && (
        <ul className="chips ask__chips" aria-label={t('ask.understood')}>
          {matched.map(e => (
            <li
              key={`${e.mention}-${e.match!.name}`}
              className="chip ask__chip"
            >
              <bdi>{e.match!.displayName}</bdi>
            </li>
          ))}
          {years && <li className="chip ask__chip">{years}</li>}
          {interpretation.genreDisplayName && (
            <li className="chip ask__chip">
              {interpretation.genreDisplayName}
            </li>
          )}
          {interpretation.strongest && (
            <li className="chip ask__chip">{t('ask.filter.strongest')}</li>
          )}
        </ul>
      )}
      {ambiguous && (
        <div
          className="ask__examples"
          role="group"
          aria-label={t('ask.didYouMean')}
        >
          <div className="chips">
            {ambiguous.alternatives.map(c => (
              <button
                key={c.name}
                type="button"
                className="chip"
                onClick={() => onAsk(query, [...chosen, c.name])}
              >
                <bdi>{c.displayName}</bdi>
                {c.subtitle && (
                  <span className="ask__chip-detail">{c.subtitle}</span>
                )}
              </button>
            ))}
          </div>
        </div>
      )}
      {response.results.length > 0 && (
        <ul className="list ask__rows">
          {response.results.slice(0, MAX_ROWS).map((row, index) => (
            <Row
              key={row.artist?.name ?? row.recording?.name ?? index}
              row={row}
              nameOf={nameOf}
              onNavigate={onNavigate}
            />
          ))}
        </ul>
      )}
      {needsExamples(response) && <Examples onAsk={q => onAsk(q)} />}
      {response.destination && (
        <div className="ask__actions">
          <Link
            className="btn btn--filled"
            to={response.destination}
            onClick={onNavigate}
          >
            {t(destinationLabel(interpretation.intent))}
          </Link>
        </div>
      )}
      <details className="more">
        <summary>{t('ask.how')}</summary>
        <div className="more__body stack">
          <p>
            {response.model.used && response.model.model
              ? t('ask.how.model', {model: response.model.model})
              : t('ask.how.parser')}
          </p>
          <p>{t('ask.how.facts')}</p>
          {response.model.configured && <p>{t('ask.how.privacy')}</p>}
        </div>
      </details>
    </>
  );
}

/** The elevated panel under the search bar. */
export function AskAnswer({state, id, onAsk, onClose, onNavigate}: Props) {
  const {t} = useI18n();
  return (
    <section
      id={id}
      className="ask"
      aria-label={t('ask.panel')}
      aria-busy={state.status === 'loading'}
      onKeyDown={event => {
        if (event.key === 'Escape') {
          event.stopPropagation();
          onClose();
        }
      }}
    >
      <div className="ask__header">
        <Icon name="spark" />
        <p className="ask__question">
          <bdi>{state.query}</bdi>
        </p>
        <button
          type="button"
          className="icon-btn ask__close"
          aria-label={t('ask.close')}
          onClick={onClose}
        >
          <Icon name="close" />
        </button>
      </div>
      {state.status === 'loading' && (
        <p className="ask__answer ask__answer--loading">{t('ask.loading')}</p>
      )}
      {state.status === 'error' && (
        <div className="stack ask__error">
          <p className="ask__answer">
            {state.error instanceof ApiError &&
            state.error.status === 'RESOURCE_EXHAUSTED'
              ? t('ask.rateLimited')
              : t('ask.error')}
          </p>
          <div>
            <button
              type="button"
              className="btn btn--tonal"
              onClick={() => onAsk(state.query)}
            >
              {t('ask.retry')}
            </button>
          </div>
        </div>
      )}
      {state.status === 'done' && (
        <Answer
          response={state.response}
          query={state.query}
          onAsk={onAsk}
          onNavigate={onNavigate}
        />
      )}
    </section>
  );
}
