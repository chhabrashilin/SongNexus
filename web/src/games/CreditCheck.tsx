/**
 * Credit check: five questions a day about who made what, each answer backed by
 * the credits (and their sources) once it is given. Answers and score stay on
 * this device; the server only checks one answer at a time.
 */
import {useEffect, useMemo, useState} from 'react';

import {idOf} from '../api/client';
import {
  checkTrivia,
  useTrivia,
  type CheckTriviaResponse,
  type TriviaQuestion,
} from '../api/discover';
import {EvidenceList} from '../components/ConnectionSheet';
import {Icon} from '../components/Icon';
import {useSnackbar} from '../components/Snackbar';
import {ErrorState, Spinner} from '../components/States';
import {hostOf} from '../components/evidence';
import {useI18n} from '../i18n/i18n';
import type {MessageId} from '../i18n/messages';

import {
  isComplete,
  loadRecord,
  nextIndex,
  recordAnswer,
  saveRecord,
  scoreOf,
  shareText,
  triviaLink,
  type TriviaRecord,
} from './trivia';

function storage(): Storage | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

function questionValues(q: TriviaQuestion) {
  return {subject: q.subject?.displayName ?? '', artist: q.artist.displayName};
}

export function CreditCheck({date, today}: {date: string; today: string}) {
  const quiz = useTrivia(date);
  if (quiz.isPending) return <Spinner />;
  if (quiz.isError || quiz.data.questions.length === 0) {
    return (
      <ErrorState error={quiz.error} onRetry={() => void quiz.refetch()} />
    );
  }
  return (
    <Quiz
      key={`${date}-${quiz.data.graphVersion}`}
      date={date}
      today={today}
      quiz={quiz.data}
    />
  );
}

function Quiz({
  date,
  today,
  quiz,
}: {
  date: string;
  today: string;
  quiz: NonNullable<ReturnType<typeof useTrivia>['data']>;
}) {
  const {t} = useI18n();
  const snackbar = useSnackbar();
  const order = useMemo(() => quiz.questions.map(q => q.id), [quiz]);
  const [record, setRecord] = useState<TriviaRecord>(() =>
    loadRecord(date, quiz.graphVersion, order, storage()),
  );
  const [started, setStarted] = useState(
    () => Object.keys(record.answers).length > 0,
  );
  const [index, setIndex] = useState(() =>
    Math.min(nextIndex(record), order.length - 1),
  );
  const [results, setResults] = useState<Record<string, CheckTriviaResponse>>(
    {},
  );
  const [pending, setPending] = useState(false);
  const [failed, setFailed] = useState(false);

  const question = quiz.questions[Math.min(index, order.length - 1)]!;
  const answer = record.answers[question.id];
  const result = results[question.id];
  const complete = isComplete(record);

  // After a reload the verdict is stored but the credits are not: fetch them again.
  useEffect(() => {
    if (!answer || result) return;
    let live = true;
    checkTrivia(date, question.id, answer.option)
      .then(r => live && setResults(prev => ({...prev, [question.id]: r})))
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [answer, result, date, question.id]);

  async function choose(option: string) {
    if (answer || pending) return;
    setPending(true);
    setFailed(false);
    try {
      const r = await checkTrivia(date, question.id, option);
      setResults(prev => ({...prev, [question.id]: r}));
      const next = recordAnswer(
        record,
        question.id,
        {option, correct: r.correct},
        today,
      );
      setRecord(next);
      saveRecord(next, storage());
    } catch {
      setFailed(true);
    } finally {
      setPending(false);
    }
  }

  const names = useMemo(() => {
    const map = new Map<string, string>();
    map.set(question.artist.name, question.artist.displayName);
    for (const o of question.options) map.set(o.name, o.displayName);
    if (result)
      map.set(result.correctOption.name, result.correctOption.displayName);
    return map;
  }, [question, result]);

  async function share() {
    const text = shareText(
      record,
      quiz.number,
      t,
      triviaLink(window.location.origin, date),
    );
    try {
      if (navigator.share) await navigator.share({text});
      else {
        await navigator.clipboard.writeText(text);
        snackbar(t('games.credit.shareCopied'));
      }
    } catch (e) {
      if (!(e instanceof DOMException && e.name === 'AbortError')) {
        snackbar(t('games.credit.shareFailed'));
      }
    }
  }

  if (!started && !complete) {
    return (
      <div className="credit-intro">
        <p className="lead">
          {t('games.credit.lead', {count: quiz.questions.length})}
        </p>
        <button className="btn btn--filled" onClick={() => setStarted(true)}>
          <Icon name="play" />
          {t('games.credit.start')}
        </button>
      </div>
    );
  }

  const last = index === order.length - 1;
  const showSummary = complete && index >= order.length;
  return (
    <div className="credit">
      <nav
        className="credit__steps"
        aria-label={t('games.credit.progress', {
          n: index + 1,
          total: order.length,
        })}
      >
        {order.map((id, i) => {
          const a = record.answers[id];
          const label = `${t('games.credit.progress', {n: i + 1, total: order.length})}: ${
            a
              ? a.correct
                ? t('games.credit.result.right')
                : t('games.credit.result.wrong')
              : t('games.credit.pending')
          }`;
          return (
            <button
              key={id}
              type="button"
              className="credit__step"
              data-state={a ? (a.correct ? 'right' : 'wrong') : 'open'}
              aria-current={i === index && !showSummary ? 'step' : undefined}
              aria-label={label}
              disabled={!a && i !== nextIndex(record)}
              onClick={() => setIndex(i)}
            >
              {a ? (
                <Icon name={a.correct ? 'check' : 'close'} size={18} />
              ) : (
                i + 1
              )}
            </button>
          );
        })}
      </nav>

      {showSummary ? (
        <div className="credit__summary" role="status">
          <p className="strapline">{t('games.credit.done')}</p>
          <p className="credit__score">
            {t('games.credit.score', {
              score: scoreOf(record),
              total: order.length,
            })}
          </p>
          <p className="credit__squares" aria-hidden="true">
            {order
              .map(id => (record.answers[id]?.correct ? '🟩' : '🟥'))
              .join('')}
          </p>
          <div className="row">
            <button className="btn btn--filled" onClick={() => void share()}>
              <Icon name="share" />
              {t('games.credit.share')}
            </button>
            <button className="btn btn--tonal" onClick={() => setIndex(0)}>
              {t('games.credit.review')}
            </button>
          </div>
        </div>
      ) : (
        <section aria-labelledby="credit-q" className="credit__question">
          <p className="strapline">
            {t('games.credit.progress', {n: index + 1, total: order.length})}
          </p>
          <h3 id="credit-q" className="credit__prompt">
            {t(question.messageId as MessageId, questionValues(question))}
          </h3>
          <ul
            className="credit__options"
            aria-label={t('games.credit.options')}
          >
            {question.options.map(option => {
              const chosen = answer?.option === option.name;
              const right = result?.correctOption.name === option.name;
              const state = !answer
                ? 'open'
                : right
                  ? 'right'
                  : chosen
                    ? 'wrong'
                    : 'idle';
              return (
                <li key={option.name}>
                  <button
                    type="button"
                    className="credit__option"
                    data-state={state}
                    aria-pressed={chosen}
                    disabled={pending || !!answer}
                    onClick={() => void choose(option.name)}
                  >
                    <span className="credit__option-name">
                      <bdi>{option.displayName}</bdi>
                    </span>
                    {state === 'right' && (
                      <span className="credit__mark">
                        <Icon name="check" size={20} />
                        {t('games.credit.result.right')}
                      </span>
                    )}
                    {state === 'wrong' && (
                      <span className="credit__mark">
                        <Icon name="close" size={20} />
                        {t('games.credit.result.wrong')}
                      </span>
                    )}
                  </button>
                </li>
              );
            })}
          </ul>
          {failed && (
            <p role="alert" className="credit__error">
              {t('games.credit.checkFailed')}
            </p>
          )}
          {answer && result && (
            <div className="credit__proof" role="status">
              <p className="credit__verdict">
                {answer.correct
                  ? t('games.credit.correct')
                  : t('games.credit.incorrect', {
                      answer: result.correctOption.displayName,
                    })}
              </p>
              {question.kind === 'WHICH_LABEL' ? (
                <>
                  <p>
                    {t('games.credit.labelFact', {
                      subject: question.subject?.displayName ?? '',
                      label: result.correctOption.displayName,
                    })}
                  </p>
                  <p className="evidence__sources">
                    {result.sources.map(s => (
                      <a
                        key={s.url}
                        href={s.url}
                        target="_blank"
                        rel="noopener noreferrer"
                      >
                        {t('connection.source', {host: hostOf(s.url)})}
                        <Icon name="external" size={14} />
                      </a>
                    ))}
                  </p>
                </>
              ) : (
                <details className="more" open>
                  <summary>{t('games.credit.proof')}</summary>
                  <div className="more__body">
                    {result.evidence.length ? (
                      <EvidenceList
                        evidence={result.evidence}
                        nameOf={n => names.get(n) ?? idOf(n)}
                      />
                    ) : (
                      <p>{t('games.credit.noEvidence')}</p>
                    )}
                  </div>
                </details>
              )}
              <button
                className="btn btn--filled"
                onClick={() => setIndex(last ? order.length : index + 1)}
              >
                {last ? t('games.credit.finish') : t('games.credit.next')}
                <Icon name="chevron" />
              </button>
            </div>
          )}
        </section>
      )}
    </div>
  );
}
