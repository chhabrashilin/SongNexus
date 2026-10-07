/**
 * Turns an evidence line from the API into a sentence.
 *
 * The server sends a message ID, both artists, their roles and the subject; the
 * client picks the wording (plan §8: "credit", never "fact"). Pure, so every
 * message is unit-tested.
 */
import type {Evidence} from '../api/client';
import type {MessageId} from '../i18n/messages';

type Translate = (
  id: MessageId,
  values?: Record<string, string | number>,
) => string;

const CONTRIBUTOR_ROLES = new Set([
  'vocal',
  'instrument',
  'performer',
  'programming',
  'arranger',
  'conductor',
  'remixer',
]);

const RELATION_MESSAGES: Record<string, {id: MessageId; first: 'from' | 'to'}> =
  {
    member: {id: 'evidence.relation.member', first: 'from'},
    group: {id: 'evidence.relation.member', first: 'to'},
    subgroup: {id: 'evidence.relation.subgroup', first: 'to'},
    person: {id: 'evidence.relation.person', first: 'from'},
    'performance name': {id: 'evidence.relation.person', first: 'to'},
    collaborator: {id: 'evidence.relation.collaborator', first: 'from'},
    project: {id: 'evidence.relation.collaborator', first: 'to'},
    'supporting musician': {id: 'evidence.relation.supporting', first: 'from'},
    teacher: {id: 'evidence.relation.teacher', first: 'from'},
    student: {id: 'evidence.relation.teacher', first: 'to'},
  };

function roleWord(role: string, t: Translate): string {
  const id = `role.${role}` as MessageId;
  return CONTRIBUTOR_ROLES.has(role) ? t(id) : t('role.other');
}

/**
 * Returns the sentence for one evidence line.
 *
 * @param nameOf resolves `artists/{id}` to a display name.
 */
export function evidenceText(
  e: Evidence,
  nameOf: (name: string) => string,
  t: Translate,
): string {
  const from = nameOf(e.fromArtist);
  const to = nameOf(e.toArtist);
  const subjectType = e.subject.name.slice(0, e.subject.name.indexOf('/'));
  const subjectFallback: Record<string, MessageId> = {
    recordings: 'subject.recording',
    releases: 'subject.release',
    labels: 'subject.label',
    relations: 'subject.relation',
  };
  const subject = e.subject.displayName
    ? `“${e.subject.displayName}”`
    : t(subjectFallback[subjectType] ?? 'subject.relation');
  const fromIs = (role: string) => e.fromRole === role;

  switch (e.messageId) {
    case 'evidence.performedTogether':
      return t('evidence.performedTogether', {from, to, subject});
    case 'evidence.featured':
      return fromIs('featured')
        ? t('evidence.featured', {featured: from, main: to, subject})
        : t('evidence.featured', {featured: to, main: from, subject});
    case 'evidence.produced':
      return fromIs('producer')
        ? t('evidence.produced', {producer: from, performer: to, subject})
        : t('evidence.produced', {producer: to, performer: from, subject});
    case 'evidence.coProduced':
      return t('evidence.coProduced', {from, to, subject});
    case 'evidence.contributed': {
      const fromContributes = CONTRIBUTOR_ROLES.has(e.fromRole);
      return t('evidence.contributed', {
        contributor: fromContributes ? from : to,
        performer: fromContributes ? to : from,
        role: roleWord(fromContributes ? e.fromRole : e.toRole, t),
        subject,
      });
    }
    case 'evidence.sampled':
      return fromIs('sampled')
        ? t('evidence.sampled', {sampled: from, performer: to, subject})
        : t('evidence.sampled', {sampled: to, performer: from, subject});
    case 'evidence.engineered':
      return fromIs('engineer')
        ? t('evidence.engineered', {engineer: from, performer: to, subject})
        : t('evidence.engineered', {engineer: to, performer: from, subject});
    case 'evidence.labelMates':
      return t('evidence.labelMates', {from, to, subject});
    case 'evidence.relation': {
      const rule = RELATION_MESSAGES[e.fromRole];
      if (!rule) return t('evidence.relation.other', {a: from, b: to});
      const [a, b] = rule.first === 'from' ? [from, to] : [to, from];
      return t(rule.id, {a, b});
    }
    default:
      return t('evidence.relation.other', {a: from, b: to});
  }
}

/** Returns a source link's host for display ("musicbrainz.org"). */
export function hostOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, '');
  } catch {
    return url;
  }
}
