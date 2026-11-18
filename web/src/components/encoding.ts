/**
 * Visual encoding of connection categories (ported from v0, palette validated).
 *
 * Any two categories can meet in the web, so the palette must separate all
 * pairs. Only three categorical hues pass that check in both themes, so the
 * three most common categories get them; the rest are neutral lines told apart
 * by dash pattern. Identity never depends on color alone.
 */
import type {Schemas} from '../api/client';

export type Category = Schemas['ConnectionCategory'];
export type Kind = Schemas['ConnectionKind'];

export interface Encoding {
  color: string;
  dash: readonly number[];
}

export const CATEGORIES: readonly Category[] = [
  'FEATURES',
  'PRODUCERS',
  'CONTRIBUTIONS',
  'BANDS',
  'SAMPLES',
  'LABELS',
  'ENGINEERING',
];

export const DEFAULT_CATEGORIES: readonly Category[] = [
  'FEATURES',
  'PRODUCERS',
  'CONTRIBUTIONS',
  'BANDS',
  'SAMPLES',
];

export const CATEGORY_ENCODING: Record<Category, Encoding> = {
  FEATURES: {color: 'var(--series-1)', dash: []},
  PRODUCERS: {color: 'var(--series-2)', dash: []},
  CONTRIBUTIONS: {color: 'var(--series-3)', dash: []},
  BANDS: {color: 'var(--neutral-strong)', dash: []},
  SAMPLES: {color: 'var(--neutral-strong)', dash: [6, 4]},
  LABELS: {color: 'var(--neutral-soft)', dash: [2, 2]},
  ENGINEERING: {color: 'var(--neutral-soft)', dash: [2, 4]},
};

export const KIND_CATEGORY: Record<Kind, Category> = {
  PERFORMED_WITH: 'FEATURES',
  PRODUCED_FOR: 'PRODUCERS',
  CO_PRODUCED: 'PRODUCERS',
  CONTRIBUTED_TO: 'CONTRIBUTIONS',
  SAMPLED: 'SAMPLES',
  MEMBER_OF: 'BANDS',
  COLLABORATION: 'BANDS',
  SUPPORTED: 'BANDS',
  TAUGHT: 'BANDS',
  LABEL_MATES: 'LABELS',
  ENGINEERED: 'ENGINEERING',
};

/** The category drawn for a connection: its first kind in category order. */
export function dominantCategory(kinds: readonly Kind[]): Category {
  const present = new Set(kinds.map(k => KIND_CATEGORY[k]));
  return CATEGORIES.find(c => present.has(c)) ?? 'BANDS';
}
