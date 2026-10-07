/**
 * Six degrees (S2, US-03): pick two artists, see the chain with evidence per step.
 * All state lives in the URL, so a shared link shows the same chain to anyone (AC-3.4).
 */
import {useEffect, useMemo, useState} from 'react';
import {Link, useSearchParams} from 'react-router';

import {idOf} from '../api/client';
import {
  useArtist,
  usePath,
  type ConnectionCategory,
  type PathMode,
} from '../api/queries';
import {usePageTitle} from '../app/Shell';
import {ArtistRow, artistPath} from '../components/ArtistRow';
import {EvidenceList} from '../components/ConnectionSheet';
import {CATEGORIES, DEFAULT_CATEGORIES} from '../components/encoding';
import {CategoryChips, GenreFilter} from '../components/Filters';
import {Icon} from '../components/Icon';
import {SearchBox} from '../components/SearchBox';
import {useSnackbar} from '../components/Snackbar';
import {EmptyState, ErrorState, SkeletonRows} from '../components/States';
import {useI18n} from '../i18n/i18n';

const STEP_MS = 450;

function readCategories(value: string | null): ConnectionCategory[] {
  const picked = (value ?? '')
    .split(',')
    .filter((c): c is ConnectionCategory =>
      (CATEGORIES as string[]).includes(c),
    );
  return picked.length ? picked : [...DEFAULT_CATEGORIES];
}

function ArtistPicker({
  label,
  artistId,
  onPick,
}: {
  label: string;
  artistId: string | null;
  onPick: (id: string) => void;
}) {
  const artist = useArtist(artistId ?? undefined);
  return (
    <div className="stack" style={{gap: 'var(--space-1)', flex: '1 1 240px'}}>
      <span className="muted" style={{font: 'var(--label-large)'}}>
        {label}
      </span>
      <SearchBox
        key={artist.data?.name ?? 'empty'}
        label={label}
        types={['ARTIST']}
        clearOnPick={false}
        initialQuery={artist.data?.displayName ?? ''}
        onPick={result => onPick(idOf(result.name))}
      />
    </div>
  );
}

export default function SixDegreesScreen() {
  const {t} = useI18n();
  const snackbar = useSnackbar();
  const [search, setSearch] = useSearchParams();
  const from = search.get('from');
  const to = search.get('to');
  const mode = (
    search.get('mode') === 'STRONGEST_LINKS'
      ? 'STRONGEST_LINKS'
      : 'FEWEST_STEPS'
  ) as PathMode;
  const categories = readCategories(search.get('categories'));
  const genres = useMemo(
    () => (search.get('genres') ?? '').split(',').filter(Boolean),
    [search],
  );
  const includeUnknown = search.get('unknown') !== '0';
  const [showFilters, setShowFilters] = useState(false);
  const [revealed, setRevealed] = useState(0);
  usePageTitle(t('path.title'));

  function update(changes: Record<string, string | null>) {
    const next = new URLSearchParams(search);
    for (const [key, value] of Object.entries(changes)) {
      if (value === null || value === '') next.delete(key);
      else next.set(key, value);
    }
    setSearch(next, {replace: true});
  }

  const same = from !== null && from === to;
  const path = usePath(
    from && to && !same
      ? {
          from,
          to,
          mode,
          categories,
          genres,
          includeUnknownGenre: includeUnknown,
          alternatives: 2,
        }
      : null,
  );
  const steps = useMemo(
    () => (path.data?.outcome === 'FOUND' ? path.data.steps : []),
    [path.data],
  );

  // Reveal the chain one step at a time; instantly when motion is reduced.
  useEffect(() => {
    const reduce = window.matchMedia(
      '(prefers-reduced-motion: reduce)',
    ).matches;
    if (reduce || steps.length === 0) {
      setRevealed(steps.length);
      return;
    }
    setRevealed(0);
    const timer = window.setInterval(() => {
      setRevealed(n => {
        if (n >= steps.length) window.clearInterval(timer);
        return Math.min(n + 1, steps.length);
      });
    }, STEP_MS);
    return () => window.clearInterval(timer);
  }, [steps]);

  const chainNames = steps.length
    ? [
        steps[0]!.fromArtist.displayName,
        ...steps.map(s => s.toArtist.displayName),
      ]
    : [];
  const names = useMemo(() => {
    const map = new Map<string, string>();
    for (const step of steps) {
      map.set(step.fromArtist.name, step.fromArtist.displayName);
      map.set(step.toArtist.name, step.toArtist.displayName);
    }
    return map;
  }, [steps]);

  async function share() {
    const url = window.location.href;
    try {
      if (navigator.share) await navigator.share({title: t('path.title'), url});
      else {
        await navigator.clipboard.writeText(url);
        snackbar(t('action.linkCopied'));
      }
    } catch {
      // The user cancelled the share sheet.
    }
  }

  return (
    <div className="stack" style={{gap: 'var(--space-5)'}}>
      <header className="stack" style={{gap: 'var(--space-2)'}}>
        <h1>{t('path.title')}</h1>
        <p className="muted">{t('path.lead')}</p>
      </header>

      <div className="row" style={{alignItems: 'flex-end'}}>
        <ArtistPicker
          label={t('path.from')}
          artistId={from}
          onPick={id => update({from: id})}
        />
        <button
          type="button"
          className="icon-btn"
          onClick={() => update({from: to, to: from})}
        >
          <Icon name="swap" label={t('path.swap')} />
        </button>
        <ArtistPicker
          label={t('path.to')}
          artistId={to}
          onPick={id => update({to: id})}
        />
      </div>

      <div className="row">
        {(['FEWEST_STEPS', 'STRONGEST_LINKS'] as const).map(m => (
          <button
            key={m}
            type="button"
            className="chip"
            aria-pressed={mode === m}
            onClick={() => update({mode: m})}
          >
            {t(`path.mode.${m}`)}
          </button>
        ))}
        <button
          type="button"
          className="icon-btn"
          aria-expanded={showFilters}
          onClick={() => setShowFilters(s => !s)}
        >
          <Icon name="tune" label={t('filter.categories')} />
        </button>
      </div>

      {showFilters && (
        <div className="card stack">
          <CategoryChips
            value={categories}
            onChange={next => update({categories: next.join(',')})}
          />
          <GenreFilter
            value={genres}
            onChange={next => update({genres: next.join(',')})}
            includeUnknown={includeUnknown}
            onIncludeUnknownChange={next =>
              update({unknown: next ? null : '0'})
            }
          />
        </div>
      )}

      {same && <p className="banner">{t('path.sameArtist')}</p>}
      {path.isFetching && !path.data && <SkeletonRows count={4} />}
      {path.isError && (
        <ErrorState error={path.error} onRetry={() => void path.refetch()} />
      )}
      {path.data?.outcome === 'NOT_CONNECTED_WITHIN_LIMIT' && (
        <EmptyState title={t('path.notConnected', {max: 6})} />
      )}
      {path.data?.outcome === 'SEARCH_LIMIT_REACHED' && (
        <EmptyState title={t('path.limitReached')} />
      )}

      {steps.length > 0 && (
        <section className="section">
          <div className="section__header">
            <h2>{t('path.steps', {count: steps.length})}</h2>
            <div className="row">
              {revealed < steps.length && (
                <button
                  type="button"
                  className="btn btn--text"
                  onClick={() => setRevealed(steps.length)}
                >
                  {t('path.skipAnimation')}
                </button>
              )}
              <button
                type="button"
                className="btn btn--tonal"
                onClick={() => void share()}
              >
                <Icon name="share" />
                {t('action.share')}
              </button>
            </div>
          </div>
          <p className="visually-hidden" aria-live="polite">
            {revealed === steps.length
              ? t('path.announce', {names: chainNames.join(', ')})
              : ''}
          </p>
          <ol className="list">
            <ArtistRow artist={steps[0]!.fromArtist} />
            {steps.slice(0, revealed).map(step => (
              <li key={step.toArtist.name} className="stack" style={{gap: 0}}>
                <div
                  className="card card--outlined"
                  style={{
                    marginInlineStart: 'var(--space-6)',
                    marginBlock: 'var(--space-1)',
                  }}
                >
                  <EvidenceList
                    evidence={step.evidence}
                    nameOf={n => names.get(n) ?? ''}
                  />
                </div>
                <ul className="list">
                  <ArtistRow artist={step.toArtist} />
                </ul>
              </li>
            ))}
          </ol>
        </section>
      )}

      {path.data &&
        path.data.alternatives.length > 0 &&
        revealed === steps.length && (
          <section className="section">
            <h2>{t('path.alternatives')}</h2>
            <ul className="list">
              {path.data.alternatives.map(route => (
                <li key={route.map(a => a.name).join('>')} className="list-row">
                  <span className="list-row__body">
                    {route.map((a, i) => (
                      <span key={a.name}>
                        {i > 0 && ' → '}
                        <Link to={artistPath(a)}>
                          <bdi>{a.displayName}</bdi>
                        </Link>
                      </span>
                    ))}
                  </span>
                </li>
              ))}
            </ul>
          </section>
        )}
    </div>
  );
}
