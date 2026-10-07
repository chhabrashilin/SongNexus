/** Every credit connecting two artists, each with its source. Evidence is one tap away (plan §8). */
import {useMemo} from 'react';

import type {Evidence} from '../api/client';
import {useConnection, type ConnectionCategory} from '../api/queries';
import {useI18n} from '../i18n/i18n';

import {hostOf, evidenceText} from './evidence';
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
