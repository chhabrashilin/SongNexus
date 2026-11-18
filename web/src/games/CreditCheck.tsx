/**
 * Credit check: five questions a day about who made what, one at a time, with
 * photo options. Each answer is checked by the server and immediately backed by
 * the credit that proves it and its source. Answers and score stay on this
 * device; the server only checks one answer at a time.
 */
import {useEffect, useMemo, useRef, useState, type CSSProperties} from 'react';

import {idOf} from '../api/client';
import {
  checkTrivia,
  useTrivia,
  type CheckTriviaResponse,
  type TriviaQuestion,
} from '../api/discover';
import {imageOf} from '../components/ArtistRow';
import {EvidenceList} from '../components/ConnectionSheet';
import {hostOf} from '../components/evidence';
import {Icon} from '../components/Icon';
import {Cover, hueOf} from '../components/Shelf';
import {useSnackbar} from '../components/Snackbar';
import {ErrorState} from '../components/States';
import {useI18n} from '../i18n/i18n';
import type {MessageId} from '../i18n/messages';

import {Leaderboards, ScoreSubmit} from './Leaderboard';
import {triviaAnswers} from './scores';
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

function typing(target: EventTarget | null): boolean {
  return (
    target instanceof HTMLElement &&
    (target.isContentEditable ||
      ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName))
  );
}

export function CreditCheck({
  date,
  today,
  onProgress,
}: {
  date: string;
  today: string;
  /** Called after each answer is saved, so the hub can refresh its summary. */
  onProgress?: () => void;
}) {
  const {t} = useI18n();
  const quiz = useTrivia(date);
  if (quiz.isPending) return <CreditSkeleton />;
  if (quiz.isError) {
    return (
      <ErrorState error={quiz.error} onRetry={() => void quiz.refetch()} />
    );
  }
  if (quiz.data.questions.length === 0) {
    return <p className="credit-empty">{t('games.credit.empty')}</p>;
  }
  return (
    <Quiz
      key={`${date}-${quiz.data.graphVersion}`}
      date={date}
      today={today}
      quiz={quiz.data}
      onProgress={onProgress}
    />
  );
}

function CreditSkeleton() {
  const {t} = useI18n();
  return (
    <div className="credit" role="status">
      <span className="visually-hidden">{t('state.loading')}</span>
      <div className="credit__question" aria-hidden="true">
        <span className="skeleton credit-skel credit-skel--line" />
        <span className="skeleton credit-skel credit-skel--title" />
        <div className="credit__options">
          {Array.from({length: 4}, (_, i) => (
            <span
              key={i}
              className="skeleton credit-skel credit-skel--option"
            />
          ))}
        </div>
      </div>
    </div>
  );
}

type Quiz = NonNullable<ReturnType<typeof useTrivia>['data']>;

function Quiz({
  date,
  today,
  quiz,
  onProgress,
}: {
  date: string;
  today: string;
  quiz: Quiz;
  onProgress?: (() => void) | undefined;
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
  const [index, setIndex] = useState(() => nextIndex(record));
  const [results, setResults] = useState<Record<string, CheckTriviaResponse>>(
    {},
  );
  const [pending, setPending] = useState(false);
  const [failed, setFailed] = useState(false);
  // Where focus goes next: the prompt after moving on, "next" after answering.
  const [focusTo, setFocusTo] = useState<'prompt' | 'next' | 'summary' | null>(
    null,
  );
  const prompt = useRef<HTMLHeadingElement>(null);
  const nextButton = useRef<HTMLButtonElement>(null);
  const summary = useRef<HTMLParagraphElement>(null);

  const complete = isComplete(record);
  const showSummary = complete && index >= order.length;
  const question = quiz.questions[Math.min(index, order.length - 1)]!;
  const answer = record.answers[question.id];
  const result = results[question.id];
  const last = index === order.length - 1;

  // After a reload the verdict is stored but the credits are not: fetch them again.
  useEffect(() => {
    if (!answer || result || showSummary) return;
    let live = true;
    checkTrivia(date, question.id, answer.option)
      .then(r => live && setResults(prev => ({...prev, [question.id]: r})))
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [answer, result, date, question.id, showSummary]);

  useEffect(() => {
    if (focusTo === 'prompt') prompt.current?.focus();
    if (focusTo === 'next' && result) nextButton.current?.focus();
    if (focusTo === 'summary') summary.current?.focus();
  }, [focusTo, result, index]);

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
      onProgress?.();
      setFocusTo('next');
    } catch {
      setFailed(true);
    } finally {
      setPending(false);
    }
  }

  function goTo(i: number) {
    setIndex(i);
    setFailed(false);
    setFocusTo(i >= order.length ? 'summary' : 'prompt');
  }

  // Number keys pick an answer.
  useEffect(() => {
    if (!started || showSummary || answer) return;
    function onKey(event: KeyboardEvent) {
      if (event.altKey || event.ctrlKey || event.metaKey) return;
      if (typing(event.target)) return;
      const n = Number(event.key);
      const option = question.options[n - 1];
      if (!Number.isInteger(n) || !option) return;
      event.preventDefault();
      void choose(option.name);
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  });

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
    const faces = quiz.questions.map(q => q.artist);
    return (
      <div className="credit-intro">
        <div className="credit-intro__faces" aria-hidden="true">
          {faces.map((artist, i) => (
            <Cover
              key={`${artist.name}-${i}`}
              name={artist.displayName}
              image={imageOf(artist)}
              round
            />
          ))}
        </div>
        <p className="credit-intro__lead">
          {t('games.credit.lead', {count: quiz.questions.length})}
        </p>
        <p className="muted">{t('games.credit.how')}</p>
        <button
          type="button"
          className="btn btn--filled"
          onClick={() => {
            setStarted(true);
            setFocusTo('prompt');
          }}
        >
          <Icon name="play" />
          {t('games.credit.start')}
        </button>
      </div>
    );
  }

  const score = scoreOf(record);
  const answers = triviaAnswers(record);
  return (
    <div className="credit">
      <nav className="credit__steps" aria-label={t('games.credit.progressNav')}>
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
              onClick={() => goTo(i)}
            >
              {a ? (
                <Icon name={a.correct ? 'check' : 'close'} size={18} />
              ) : (
                i + 1
              )}
            </button>
          );
        })}
        {complete && (
          <button
            type="button"
            className="credit__step credit__step--score"
            aria-current={showSummary ? 'step' : undefined}
            onClick={() => goTo(order.length)}
          >
            {t('games.credit.score.short', {score, total: order.length})}
          </button>
        )}
      </nav>

      {showSummary ? (
        <div className="credit__summary" role="status">
          <p className="strapline">{t('games.credit.done')}</p>
          <p className="credit__score" ref={summary} tabIndex={-1}>
            {t('games.credit.score', {score, total: order.length})}
          </p>
          <p className="credit__verdict-line">
            {score === order.length
              ? t('games.credit.verdict.perfect')
              : score >= order.length - 1
                ? t('games.credit.verdict.great')
                : t('games.credit.verdict.more')}
          </p>
          <p className="credit__squares" aria-hidden="true">
            {order.map(id => (
              <span
                key={id}
                className="credit__square"
                data-state={record.answers[id]?.correct ? 'right' : 'wrong'}
              />
            ))}
          </p>
          <div className="credit__summary-actions">
            <button
              type="button"
              className="btn btn--filled"
              onClick={() => void share()}
            >
              <Icon name="share" />
              {t('games.credit.share')}
            </button>
            <button
              type="button"
              className="btn btn--tonal"
              onClick={() => goTo(0)}
            >
              {t('games.credit.review')}
            </button>
          </div>
          <ScoreSubmit
            game="TRIVIA"
            date={date}
            today={today}
            play={answers ? {game: 'TRIVIA', date, answers} : null}
          />
          <Leaderboards game="TRIVIA" date={date} placement="result" />
        </div>
      ) : (
        <section
          aria-labelledby="credit-q"
          className="credit__question"
          style={{'--hue': hueOf(question.artist.displayName)} as CSSProperties}
        >
          <div className="credit__about">
            <Cover
              name={question.artist.displayName}
              image={imageOf(question.artist)}
              round
            />
            <div className="credit__about-text">
              <p className="strapline">
                {t('games.credit.progress', {
                  n: index + 1,
                  total: order.length,
                })}
                {' · '}
                {t(`games.credit.kind.${question.kind}`)}
              </p>
              <h3
                id="credit-q"
                className="credit__prompt"
                ref={prompt}
                tabIndex={-1}
              >
                <bdi>
                  {t(question.messageId as MessageId, questionValues(question))}
                </bdi>
              </h3>
            </div>
          </div>
          <ul
            className="credit__options"
            aria-label={t('games.credit.options')}
          >
            {question.options.map((option, i) => {
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
                    <Cover
                      name={option.displayName}
                      image={imageOf(option)}
                      round={question.kind !== 'WHICH_LABEL'}
                    />
                    <span className="credit__option-text">
                      <span className="credit__option-name">
                        <bdi>{option.displayName}</bdi>
                      </span>
                      {option.disambiguation && (
                        <span className="credit__option-sub">
                          <bdi>{option.disambiguation}</bdi>
                        </span>
                      )}
                    </span>
                    {state === 'open' && (
                      <span className="kbd credit__key" aria-hidden="true">
                        {i + 1}
                      </span>
                    )}
                    {state === 'right' && (
                      <span className="credit__mark">
                        <Icon name="check" size={20} />
                        <span className="visually-hidden">
                          {t('games.credit.result.right')}
                        </span>
                      </span>
                    )}
                    {state === 'wrong' && (
                      <span className="credit__mark">
                        <Icon name="close" size={20} />
                        <span className="visually-hidden">
                          {t('games.credit.result.wrong')}
                        </span>
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
          <div className="credit__proof" role="status">
            {answer && result && (
              <>
                <p
                  className="credit__verdict"
                  data-state={answer.correct ? 'right' : 'wrong'}
                >
                  <Icon name={answer.correct ? 'check' : 'close'} />
                  <bdi>
                    {answer.correct
                      ? t('games.credit.correct')
                      : t('games.credit.incorrect', {
                          answer: result.correctOption.displayName,
                        })}
                  </bdi>
                </p>
                <div className="credit__evidence">
                  <p className="credit__evidence-label">
                    {t('games.credit.proof')}
                  </p>
                  {question.kind === 'WHICH_LABEL' ? (
                    <>
                      <p>
                        <bdi>
                          {t('games.credit.labelFact', {
                            subject: question.subject?.displayName ?? '',
                            label: result.correctOption.displayName,
                          })}
                        </bdi>
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
                  ) : result.evidence.length ? (
                    <EvidenceList
                      evidence={result.evidence}
                      nameOf={n => names.get(n) ?? idOf(n)}
                    />
                  ) : (
                    <p>{t('games.credit.noEvidence')}</p>
                  )}
                </div>
                <button
                  ref={nextButton}
                  type="button"
                  className="btn btn--filled"
                  onClick={() => goTo(last ? order.length : index + 1)}
                >
                  {last ? t('games.credit.finish') : t('games.credit.next')}
                  <Icon name="chevron" />
                </button>
              </>
            )}
          </div>
        </section>
      )}
    </div>
  );
}
