/**
 * Credit check, client side: the answers a listener gave, the score, the daily
 * streak and the share text. Pure and unit-tested. Like the daily puzzle,
 * progress lives on this device; the server never stores who answered what.
 */
import {addDays} from '../play/game';

export interface TriviaAnswer {
  option: string;
  correct: boolean;
}

export interface TriviaRecord {
  date: string;
  graphVersion: string;
  /** Question IDs in the order asked, so the share text keeps its shape. */
  order: string[];
  answers: Record<string, TriviaAnswer>;
  /** The day the last answer was given; a streak counts only same-day finishes. */
  finishedOn?: string;
}

export const TRIVIA_STORAGE_KEY = 'songnexus.creditCheck.v1';

export function newRecord(
  date: string,
  graphVersion: string,
  order: string[],
): TriviaRecord {
  return {date, graphVersion, order, answers: {}};
}

export function answeredCount(record: TriviaRecord): number {
  return record.order.filter(id => record.answers[id]).length;
}

export function isComplete(record: TriviaRecord): boolean {
  return (
    record.order.length > 0 && answeredCount(record) === record.order.length
  );
}

export function scoreOf(record: TriviaRecord): number {
  return record.order.filter(id => record.answers[id]?.correct).length;
}

/** Records an answer once; a question cannot be answered twice. */
export function recordAnswer(
  record: TriviaRecord,
  question: string,
  answer: TriviaAnswer,
  today: string,
): TriviaRecord {
  if (!record.order.includes(question) || record.answers[question]) {
    return record;
  }
  const next = {...record, answers: {...record.answers, [question]: answer}};
  return isComplete(next) ? {...next, finishedOn: today} : next;
}

/** The first unanswered question's index (the length when finished). */
export function nextIndex(record: TriviaRecord): number {
  const i = record.order.findIndex(id => !record.answers[id]);
  return i === -1 ? record.order.length : i;
}

export type ShareTranslate = (
  id: 'games.credit.share.text',
  values: {number: number; score: number; total: number},
) => string;

/** "Credit check #12 · 4/5 🟩🟩🟥🟩🟩": the shape of the result, never the questions or answers. */
export function shareText(
  record: TriviaRecord,
  number: number,
  t: ShareTranslate,
  link?: string,
): string {
  const squares = record.order
    .map(id => {
      const answer = record.answers[id];
      return answer ? (answer.correct ? '🟩' : '🟥') : '⬜';
    })
    .join('');
  const head = t('games.credit.share.text', {
    number,
    score: scoreOf(record),
    total: record.order.length,
  });
  return [`${head} ${squares}`, ...(link ? [link] : [])].join('\n');
}

export function triviaLink(origin: string, date: string): string {
  return new URL(`/games?date=${encodeURIComponent(date)}`, origin).href;
}

function validRecord(value: unknown): value is TriviaRecord {
  if (!value || typeof value !== 'object') return false;
  const r = value as TriviaRecord;
  return (
    typeof r.date === 'string' &&
    /^\d{4}-\d{2}-\d{2}$/.test(r.date) &&
    typeof r.graphVersion === 'string' &&
    Array.isArray(r.order) &&
    r.order.every(id => typeof id === 'string') &&
    !!r.answers &&
    typeof r.answers === 'object' &&
    Object.values(r.answers).every(
      a => a && typeof a.option === 'string' && typeof a.correct === 'boolean',
    )
  );
}

/** Malformed or unavailable storage cannot prevent playing. */
export function loadRecords(
  storage: Pick<Storage, 'getItem'> | null,
): TriviaRecord[] {
  try {
    const value: unknown = JSON.parse(
      storage?.getItem(TRIVIA_STORAGE_KEY) ?? '[]',
    );
    return Array.isArray(value) ? value.filter(validRecord) : [];
  } catch {
    return [];
  }
}

export function loadRecord(
  date: string,
  graphVersion: string,
  order: string[],
  storage: Pick<Storage, 'getItem'> | null,
): TriviaRecord {
  return (
    loadRecords(storage).find(
      r =>
        r.date === date &&
        r.graphVersion === graphVersion &&
        r.order.join() === order.join(),
    ) ?? newRecord(date, graphVersion, order)
  );
}

export function saveRecord(
  record: TriviaRecord,
  storage: Pick<Storage, 'getItem' | 'setItem'> | null,
): void {
  try {
    const rest = loadRecords(storage).filter(r => r.date !== record.date);
    storage?.setItem(TRIVIA_STORAGE_KEY, JSON.stringify([...rest, record]));
  } catch {
    // Storage full or blocked: the quiz still works for this visit.
  }
}

export function computeTriviaStats(records: TriviaRecord[], today: string) {
  const byDate = new Map(
    records.filter(r => r.date <= today).map(r => [r.date, r]),
  );
  const done = [...byDate.values()].filter(isComplete);
  const onDay = (r: TriviaRecord | undefined) =>
    !!r && isComplete(r) && r.finishedOn === r.date;
  let currentStreak = 0;
  let day = onDay(byDate.get(today)) ? today : addDays(today, -1);
  while (onDay(byDate.get(day))) {
    currentStreak++;
    day = addDays(day, -1);
  }
  let maxStreak = 0;
  let run = 0;
  let previous = '';
  for (const key of [...byDate.keys()].sort()) {
    if (!onDay(byDate.get(key))) {
      run = 0;
      previous = '';
      continue;
    }
    run = previous && addDays(previous, 1) === key ? run + 1 : 1;
    previous = key;
    maxStreak = Math.max(maxStreak, run);
  }
  const total = done.reduce((sum, r) => sum + scoreOf(r), 0);
  return {
    played: done.length,
    perfect: done.filter(r => scoreOf(r) === r.order.length).length,
    average: done.length ? Math.round((10 * total) / done.length) / 10 : 0,
    currentStreak,
    maxStreak,
  };
}
