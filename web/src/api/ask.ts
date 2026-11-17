/**
 * Ask (ADR 0008): a question typed into the search bar, answered from our data.
 *
 * The server reads the question (its own parser, or a model that only picks an
 * intent) and answers from the graph and credits. Only the question text and
 * any "Did you mean" picks are sent. The helpers here are pure, so the wording
 * rules are unit-tested.
 */
import {useMutation} from '@tanstack/react-query';

import {messages, type MessageId} from '../i18n/messages';

import {api, unwrap, type Schemas} from './client';

export type AskResponse = Schemas['AskResponse'];
export type AskEntity = Schemas['AskEntity'];
export type AskRow = Schemas['AskRow'];
export type AskIntent = Schemas['AskIntent'];

export interface AskInput {
  query: string;
  choices?: string[];
}

export function useAsk() {
  return useMutation({
    mutationFn: ({query, choices = []}: AskInput) =>
      unwrap(api.POST('/v1/catalog:ask', {body: {query, choices}})),
  });
}

const QUESTION_START =
  /^(who|whom|what|which|how|why|when|where|did|does|do|is|are|was|were|has|have|can|could|should|would|will|list|show|tell|find|compare|explore)\b/i;
const QUESTION_SIGNS =
  /\?|\s(vs\.?|versus|->|→)\s|\b(connected|linked|related|produced|featured|collaborators?|producers|similar|between|credits)\b/i;
/** More words than a name usually has: worth asking about. */
const MANY_WORDS = 4;

/** Whether text reads like a question rather than a name (decides when "Ask" leads the list). */
export function readsLikeQuestion(text: string): boolean {
  const trimmed = text.trim();
  if (!trimmed) return false;
  if (QUESTION_START.test(trimmed) || QUESTION_SIGNS.test(trimmed)) return true;
  return trimmed.split(/\s+/).length >= MANY_WORDS;
}

/** The server's message ID, if the client knows it (an unknown one reads as "not understood"). */
export function answerMessage(id: string): MessageId {
  return id in messages ? (id as MessageId) : 'ask.answer.unknown';
}

type Translate = (
  id: MessageId,
  values?: Record<string, string | number>,
) => string;

/**
 * Turns answer parameters into message values: a name list becomes one phrase
 * ("A, B, C and 74 others"), in the viewer's language.
 */
export function answerValues(
  params: AskResponse['answer']['params'],
  formatList: (items: string[]) => string,
  t: Translate,
): Record<string, string | number> {
  const values: Record<string, string | number> = {};
  const more = typeof params.more === 'number' ? params.more : 0;
  for (const [key, value] of Object.entries(params)) {
    if (Array.isArray(value)) {
      const items =
        key === 'names' && more > 0
          ? [...value, t('ask.others', {count: more})]
          : value;
      values[key] = formatList(items);
    } else {
      values[key] = value;
    }
  }
  return values;
}

/** The answer as one sentence. */
export function answerText(
  answer: AskResponse['answer'],
  formatList: (items: string[]) => string,
  t: Translate,
): string {
  return t(
    answerMessage(answer.messageId),
    answerValues(answer.params, formatList, t),
  );
}

/** Label of the button that opens the full answer in the app. */
export function destinationLabel(intent: AskIntent): MessageId {
  return `ask.go.${intent}` as MessageId;
}

/** Example questions, shown when a question isn't understood. */
export const EXAMPLES: MessageId[] = [
  'ask.example.path',
  'ask.example.produced',
  'ask.example.compare',
  'ask.example.collaborators',
  'ask.example.like',
];

/** Whether an answer could not use the question (show the examples). */
export function needsExamples(response: AskResponse): boolean {
  return [
    'ask.answer.unknown',
    'ask.answer.nothing',
    'ask.answer.notFound',
    'ask.answer.genreNotFound',
  ].includes(response.answer.messageId);
}

/** The entity whose name needs a pick ("Did you mean …"), if any. */
export function ambiguousEntity(response: AskResponse): AskEntity | undefined {
  return response.entities.find(e => e.status === 'AMBIGUOUS');
}

/** A short label for a filter the question applied (years), or null. */
export function yearLabel(
  start: number | null | undefined,
  end: number | null | undefined,
  t: Translate,
): string | null {
  if (start && end) {
    return start === end
      ? String(start)
      : t('ask.filter.years', {from: start, to: end});
  }
  if (start) return t('ask.filter.since', {from: start});
  if (end) return t('ask.filter.until', {to: end});
  return null;
}
