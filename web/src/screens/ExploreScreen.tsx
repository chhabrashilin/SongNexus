/**
 * Explore (S1, US-02/06): start from an artist, expand connections, tap a line
 * for its evidence. The list view carries the same content as the canvas, for
 * keyboard and screen-reader users (AC-2.3).
 */
import {useQueryClient} from '@tanstack/react-query';
import {
  useCallback,
  useEffect,
  useMemo,
  useReducer,
  useRef,
  useState,
} from 'react';
import {Link, useNavigate, useParams} from 'react-router';

import {idOf} from '../api/client';
import {
  fetchConnections,
  useArtist,
  type ConnectionCategory,
} from '../api/queries';
import {usePageTitle} from '../app/Shell';
import {ConnectionSheet} from '../components/ConnectionSheet';
import {DEFAULT_CATEGORIES} from '../components/encoding';
import {CategoryChips, GenreFilter} from '../components/Filters';
import {Icon} from '../components/Icon';
import {SearchBox} from '../components/SearchBox';
import {EmptyState, ErrorState, Spinner} from '../components/States';
import {
  ConnectionWeb,
  type ConnectionWebHandle,
} from '../explore/ConnectionWeb';
import {
  emptyGraph,
  genreCoverage,
  graphReducer,
  neighborsOf,
  type GraphState,
} from '../explore/graphState';
import {useI18n} from '../i18n/i18n';

const FIRST_PAGE = 25;

function ListView({
  state,
  onExpand,
  onShowEvidence,
}: {
  state: GraphState;
  onExpand: (id: string, more: boolean) => void;
  onShowEvidence: (a: string, b: string) => void;
}) {
  const {t} = useI18n();

  function branch(id: string, path: Set<string>) {
    const expansion = state.expansions[id];
    const children = neighborsOf(state, id).filter(n => !path.has(n.node.id));
    return (
      <ul
        className="list"
        style={{paddingInlineStart: path.size > 1 ? 'var(--space-5)' : 0}}
      >
        {children.map(({node, edge}) => (
          <li key={node.id}>
            <div className="row" style={{flexWrap: 'nowrap'}}>
              <button
                type="button"
                className="list-row"
                style={{flex: 1}}
                aria-expanded={node.expanded}
                onClick={() => onExpand(node.id, false)}
              >
                <span className="list-row__body">
                  <span className="list-row__title">
                    <bdi>{node.name}</bdi>
                  </span>
                  <span className="list-row__subtitle">
                    {t('connection.strength', {strength: edge.strength})}
                  </span>
                </span>
                <span className="visually-hidden">
                  {t('explore.expand', {name: node.name})}
                </span>
              </button>
              <button
                type="button"
                className="icon-btn"
                onClick={() => onShowEvidence(id, node.id)}
              >
                <Icon
                  name="chevron"
                  label={t('connection.showEvidence', {name: node.name})}
                />
              </button>
            </div>
            {node.expanded &&
              path.size < 4 &&
              branch(node.id, new Set([...path, node.id]))}
          </li>
        ))}
        {expansion?.nextPageToken && (
          <li>
            <button
              type="button"
              className="btn btn--text"
              onClick={() => onExpand(id, true)}
            >
              {t('explore.truncated', {
                shown: expansion.shown,
                total: expansion.total,
              })}{' '}
              · {t('action.showMore')}
            </button>
          </li>
        )}
      </ul>
    );
  }

  return state.centerId
    ? branch(state.centerId, new Set([state.centerId]))
    : null;
}

export default function ExploreScreen() {
  const {t} = useI18n();
  const navigate = useNavigate();
  const {id} = useParams();
  const center = useArtist(id);
  const queryClient = useQueryClient();
  const [state, dispatch] = useReducer(graphReducer, emptyGraph);
  const [categories, setCategories] = useState<ConnectionCategory[]>([
    ...DEFAULT_CATEGORIES,
  ]);
  const [genres, setGenres] = useState<string[]>([]);
  const [includeUnknown, setIncludeUnknown] = useState(true);
  const [view, setView] = useState<'web' | 'list'>('web');
  const [selected, setSelected] = useState<string | null>(null);
  const [evidence, setEvidence] = useState<[string, string] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [attempt, setAttempt] = useState(0);
  const [showFilters, setShowFilters] = useState(false);
  const web = useRef<ConnectionWebHandle>(null);
  usePageTitle(
    center.data
      ? `${t('explore.title')}: ${center.data.displayName}`
      : t('explore.title'),
  );

  const params = useMemo(
    () => ({categories, genres, includeUnknownGenre: includeUnknown}),
    [categories, genres, includeUnknown],
  );

  const load = useCallback(
    (artistId: string, pageToken = '') =>
      queryClient.fetchQuery({
        queryKey: [
          'connections',
          artistId,
          {...params, pageSize: FIRST_PAGE, pageToken},
        ],
        queryFn: () =>
          fetchConnections(artistId, {
            ...params,
            pageSize: FIRST_PAGE,
            pageToken,
          }),
        staleTime: 5 * 60_000,
      }),
    [params, queryClient],
  );

  // (Re)start whenever the center or the filters change.
  useEffect(() => {
    const artist = center.data;
    if (!artist) return;
    let active = true;
    setError(null);
    setSelected(null);
    load(idOf(artist.name))
      .then(page => active && dispatch({type: 'start', center: artist, page}))
      .catch((e: unknown) => active && setError(e));
    return () => {
      active = false;
    };
  }, [center.data, load, attempt]);

  const expand = useCallback(
    (nodeId: string, more: boolean) => {
      const token = more ? (state.expansions[nodeId]?.nextPageToken ?? '') : '';
      if (!more && state.nodes[nodeId]?.expanded) {
        setSelected(nodeId);
        return;
      }
      load(nodeId, token)
        .then(page =>
          dispatch({type: 'expand', id: nodeId, page, append: more}),
        )
        .catch((e: unknown) => setError(e));
    },
    [load, state.expansions, state.nodes],
  );

  const nodes = useMemo(() => Object.values(state.nodes), [state.nodes]);
  const edges = useMemo(() => Object.values(state.edges), [state.edges]);
  const selectedNode = selected ? state.nodes[selected] : undefined;
  const selectedExpansion = selected ? state.expansions[selected] : undefined;

  if (!id) {
    return (
      <div className="stack">
        <h1>{t('explore.title')}</h1>
        <p className="muted">{t('explore.lead')}</p>
        <SearchBox
          types={['ARTIST']}
          autoFocus
          onPick={r => void navigate(`/explore/${idOf(r.name)}`)}
        />
      </div>
    );
  }
  if (center.isPending) return <Spinner />;
  if (center.isError)
    return (
      <ErrorState error={center.error} onRetry={() => void center.refetch()} />
    );

  return (
    <div className="stack">
      <div className="section__header">
        <h1>
          <bdi>{center.data.displayName}</bdi>
        </h1>
        <div className="row" role="group" aria-label={t('explore.title')}>
          <button
            type="button"
            className="chip"
            aria-pressed={view === 'web'}
            onClick={() => setView('web')}
          >
            {t('explore.view.web')}
          </button>
          <button
            type="button"
            className="chip"
            aria-pressed={view === 'list'}
            onClick={() => setView('list')}
          >
            {t('explore.view.list')}
          </button>
          <button
            type="button"
            className="icon-btn"
            aria-expanded={showFilters}
            onClick={() => setShowFilters(s => !s)}
          >
            <Icon name="tune" label={t('filter.categories')} />
          </button>
        </div>
      </div>

      {showFilters && (
        <div className="card stack">
          <CategoryChips value={categories} onChange={setCategories} />
          <GenreFilter
            value={genres}
            onChange={setGenres}
            includeUnknown={includeUnknown}
            onIncludeUnknownChange={setIncludeUnknown}
            coverage={genreCoverage(state)}
          />
        </div>
      )}

      {Boolean(error) && (
        <ErrorState error={error} onRetry={() => setAttempt(n => n + 1)} />
      )}
      {state.centerId && edges.length === 0 && !error && (
        <EmptyState title={t('explore.empty')} />
      )}
      {state.capped > 0 && (
        <p className="banner">
          {t('explore.truncated', {
            shown: nodes.length,
            total: nodes.length + state.capped,
          })}
        </p>
      )}

      {view === 'web' ? (
        <div
          className="card card--outlined"
          style={{
            position: 'relative',
            blockSize: 'min(70dvh, 640px)',
            padding: 0,
            overflow: 'hidden',
          }}
        >
          <ConnectionWeb
            ref={web}
            nodes={nodes}
            edges={edges}
            centerId={state.centerId}
            selectedId={selected}
            label={t('explore.canvasLabel', {name: center.data.displayName})}
            onSelectNode={nodeId => setSelected(nodeId)}
            onSelectEdge={(a, b) => setEvidence([a, b])}
          />
          <div
            className="row"
            style={{
              position: 'absolute',
              insetBlockStart: 8,
              insetInlineEnd: 8,
            }}
          >
            <button
              type="button"
              className="icon-btn"
              onClick={() => web.current?.fit()}
            >
              <Icon name="fit" label={t('explore.fit')} />
            </button>
          </div>
          {selectedNode && (
            <div
              className="card"
              style={{
                position: 'absolute',
                insetInline: 8,
                insetBlockEnd: 8,
                boxShadow: 'var(--elevation-3)',
              }}
            >
              <div className="section__header">
                <h2>
                  <bdi>{selectedNode.name}</bdi>
                </h2>
                <button
                  type="button"
                  className="icon-btn"
                  onClick={() => setSelected(null)}
                >
                  <Icon name="close" label={t('action.close')} />
                </button>
              </div>
              <div className="row" style={{marginBlockStart: 'var(--space-2)'}}>
                {!selectedNode.expanded && (
                  <button
                    type="button"
                    className="btn btn--filled"
                    onClick={() => expand(selectedNode.id, false)}
                  >
                    {t('explore.expand', {name: selectedNode.name})}
                  </button>
                )}
                {selectedExpansion?.nextPageToken && (
                  <button
                    type="button"
                    className="btn btn--tonal"
                    onClick={() => expand(selectedNode.id, true)}
                  >
                    {t('action.showMore')}
                  </button>
                )}
                <Link
                  className="btn btn--text"
                  to={`/artist/${selectedNode.id}`}
                >
                  {selectedNode.name}
                  <Icon name="chevron" size={18} />
                </Link>
              </div>
            </div>
          )}
        </div>
      ) : (
        <ListView
          state={state}
          onExpand={expand}
          onShowEvidence={(a, b) => setEvidence([a, b])}
        />
      )}

      <ConnectionSheet
        a={evidence?.[0] ?? null}
        b={evidence?.[1] ?? null}
        categories={categories}
        onClose={() => setEvidence(null)}
      />
    </div>
  );
}
