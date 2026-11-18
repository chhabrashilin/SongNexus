/**
 * Why an artist is recommended, in words. The API sends each reason as a kind
 * with values (ADR: every claim is backed); this turns them into short lines in
 * a fixed order: shared collaborators first (the strongest, checkable link),
 * then listeners in common, then a shared label.
 */
import type {Schemas} from '../api/client';
import type {MessageId} from '../i18n/messages';

export type Reason = Schemas['RecommendationReason'];

export interface ReasonLine {
  kind: Reason['kind'];
  messageId: MessageId;
  values: Record<string, string | number>;
  /** Shared collaborators, strongest first (at most three). */
  via: Schemas['ArtistSummary'][];
}

const ORDER: Reason['kind'][] = [
  'SHARED_COLLABORATORS',
  'LISTENERS_IN_COMMON',
  'SAME_LABEL',
];

function count(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) && value > 0
    ? value
    : null;
}

/** The lines for one recommendation; reasons we can't phrase honestly are left out. */
export function explain(reasons: Reason[]): ReasonLine[] {
  const lines: ReasonLine[] = [];
  for (const reason of [...reasons].sort(
    (a, b) => ORDER.indexOf(a.kind) - ORDER.indexOf(b.kind),
  )) {
    if (reason.kind === 'SHARED_COLLABORATORS') {
      const n = count(reason.params.count) ?? (reason.via.length || null);
      if (n === null) continue;
      lines.push({
        kind: reason.kind,
        messageId: 'recommend.shared',
        values: {count: n},
        via: reason.via.slice(0, 3),
      });
    } else if (reason.kind === 'LISTENERS_IN_COMMON') {
      lines.push({
        kind: reason.kind,
        messageId:
          reason.params.strength === 'STRONG'
            ? 'recommend.listeners.strong'
            : 'recommend.listeners',
        values: {},
        via: [],
      });
    } else if (reason.kind === 'SAME_LABEL') {
      const label =
        reason.label?.displayName ??
        (typeof reason.params.label === 'string' ? reason.params.label : null);
      if (!label) continue;
      lines.push({
        kind: reason.kind,
        messageId: 'recommend.label',
        values: {label},
        via: [],
      });
    }
  }
  return lines;
}

/** "Lil Wayne, JAŸ-Z and Snoop Dogg" in the interface language. */
export function listOf(names: string[], locale: string): string {
  try {
    return new Intl.ListFormat(locale === 'ar-XB' ? 'ar' : locale, {
      style: 'long',
      type: 'conjunction',
    }).format(names);
  } catch {
    return names.join(', ');
  }
}
