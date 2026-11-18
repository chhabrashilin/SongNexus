/** Every credit connecting two artists, each with its source. Evidence is one tap away (plan §8). */
import {useMemo, useState} from 'react';
import {Link} from 'react-router';

import type {Evidence} from '../api/client';
import {useConnection, type ConnectionCategory} from '../api/queries';
import {useI18n} from '../i18n/i18n';

import {CATEGORIES, KIND_CATEGORY} from './encoding';
import {hostOf, evidenceText} from './evidence';
import {Swatch} from './Filters';
import {Icon} from './Icon';
import {Sheet} from './Sheet';
import {ErrorState, SkeletonRows} from './States';

export function EvidenceList({
  evidence,
  nameOf,
}: {
  evidence: Evidence[];
  nameOf: (name: string) => string;
}) {
  const {t} = useI18n();
  return (
    <ul className="list">
      {evidence.map((e, index) => (
        <li key={`${e.subject.name}-${e.kind}-${index}`} className="evidence">
          <span>{evidenceText(e, nameOf, t)}</span>
          {subjectPath(e.subject.name) && (
            <Link to={subjectPath(e.subject.name)!}>
              {t('connection.openSubject')}
              {e.subject.displayName ? ` “${e.subject.displayName}”` : ''}
            </Link>
          )}
          {e.sources.length > 0 && (
            <span className="evidence__sources">
              {e.sources.map(source => (
                <a
                  key={source.url}
                  href={source.url}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  {t('connection.source', {host: hostOf(source.url)})}
                  <Icon name="external" size={14} />
                </a>
              ))}
            </span>
          )}
        </li>
      ))}
    </ul>
  );
}

/** The in-app page for an evidence subject, when there is one. */
export function subjectPath(name: string): string | null {
  const [collection, id] = name.split('/');
  if (!id) return null;
  if (collection === 'recordings') return `/song/${id}`;
  if (collection === 'labels') return `/label/${id}`;
  return null;
}

/** How many credits are listed before "show all". */
const EVIDENCE_PREVIEW = 5;

/**
 * The credits behind one connection, for use inside a panel: the count and the
 * kinds of connection first, then the credits (a few, with the rest one tap away).
 */
export function ConnectionEvidence({
  a,
  b,
  categories,
}: {
  a: string;
  b: string;
  categories: ConnectionCategory[];
}) {
  const {t} = useI18n();
  const detail = useConnection(a, b, categories);
  const [all, setAll] = useState(false);
  const names = useMemo(() => {
    const map = new Map<string, string>();
    if (detail.data) {
      map.set(detail.data.artist.name, detail.data.artist.displayName);
      map.set(detail.data.other.name, detail.data.other.displayName);
    }
    return map;
  }, [detail.data]);

  if (detail.isPending) return <SkeletonRows count={3} />;
  if (detail.isError)
    return (
      <ErrorState error={detail.error} onRetry={() => void detail.refetch()} />
    );
  const {evidence, kinds} = detail.data;
  const present = new Set(kinds.map(kind => KIND_CATEGORY[kind]));
  const shown = all ? evidence : evidence.slice(0, EVIDENCE_PREVIEW);
  return (
    <div className="connection-evidence">
      <p className="connection-evidence__count">
        {t('connection.evidenceCount', {count: evidence.length})}
      </p>
      <ul className="connection-evidence__kinds">
        {CATEGORIES.filter(category => present.has(category)).map(category => (
          <li key={category}>
            <Swatch category={category} />
            {t(`category.${category}`)}
          </li>
        ))}
      </ul>
      <EvidenceList evidence={shown} nameOf={n => names.get(n) ?? ''} />
      {!all && evidence.length > EVIDENCE_PREVIEW && (
        <button
          type="button"
          className="btn btn--tonal"
          onClick={() => setAll(true)}
        >
          {t('connection.showAll', {count: evidence.length})}
        </button>
      )}
    </div>
  );
}

interface Props {
  a: string | null;
  b: string | null;
  categories: ConnectionCategory[];
  onClose: () => void;
}

export function ConnectionSheet({a, b, categories, onClose}: Props) {
  const {t} = useI18n();
  const detail = useConnection(a ?? undefined, b ?? undefined, categories);
  const names = useMemo(() => {
    const map = new Map<string, string>();
    if (detail.data) {
      map.set(detail.data.artist.name, detail.data.artist.displayName);
      map.set(detail.data.other.name, detail.data.other.displayName);
    }
    return map;
  }, [detail.data]);
  const title = detail.data
    ? t('connection.evidenceTitle', {
        a: detail.data.artist.displayName,
        b: detail.data.other.displayName,
      })
    : t('state.loading');

  return (
    <Sheet open={Boolean(a && b)} title={title} onClose={onClose}>
      {detail.isPending && <SkeletonRows count={3} />}
      {detail.isError && (
        <ErrorState
          error={detail.error}
          onRetry={() => void detail.refetch()}
        />
      )}
      {detail.data && (
        <>
          <p className="muted" title={t('connection.strengthHelp')}>
            {t('connection.evidenceCount', {
              count: detail.data.evidence.length,
            })}
            {' · '}
            {t('connection.strength', {strength: detail.data.strength})}
          </p>
          <EvidenceList
            evidence={detail.data.evidence}
            nameOf={n => names.get(n) ?? ''}
          />
        </>
      )}
    </Sheet>
  );
}
