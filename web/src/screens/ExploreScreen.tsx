/**
 * The connection web (S1, US-02/06): start from an artist, open their
 * connections, select a line for the credits behind it.
 *
 * The page is the web: the canvas fills it, tools float over it, and a details
 * panel answers "who is this?" and "why are they linked?" without leaving. The
 * list view carries the same content for keyboard and screen-reader users
 * (AC-2.3).
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
import {Link, useParams} from 'react-router';

import {idOf} from '../api/client';
import {
  fetchConnections,
  useArtist,
  type ConnectionCategory,
} from '../api/queries';
import {NO_GENRE_FILTER, type GenreSelection} from '../app/genreSelection';
import {usePageTitle} from '../app/Shell';
import {ConnectionEvidence} from '../components/ConnectionSheet';
import {
  CATEGORIES,
  DEFAULT_CATEGORIES,
  dominantCategory,
} from '../components/encoding';
import {CategoryChips, GenreFilter, Swatch} from '../components/Filters';
import {Icon} from '../components/Icon';
import {Cover} from '../components/Shelf';
import {EmptyState, ErrorState, Spinner} from '../components/States';
import {
  ConnectionWeb,
  type ConnectionWebHandle,
} from '../explore/ConnectionWeb';
import {
  edgeKey,
  emptyGraph,
  genreCoverage,
  graphReducer,
  strongestUnexpanded,
  neighborsOf,
  type GraphState,
  type WebEdge,
  type WebNode,
} from '../explore/graphState';
import {useI18n} from '../i18n/i18n';

const FIRST_PAGE = 25;
/** How many artists "expand the strongest" opens at once. */
const EXPAND_STRONGEST = 5;
/** "Only show connections with at least this many credits." */
const MIN_CREDITS = [1, 3, 10] as const;
/** Rows shown in the panel before "show all". */
const PANEL_ROWS = 6;

type Selection =
  {kind: 'node'; id: string} | {kind: 'edge'; a: string; b: string} | null;

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
      <ul className={path.size > 1 ? 'list web-list__branch' : 'list'}>
        {children.map(({node, edge}) => (
          <li key={node.id}>
            <div className="web-list__row">
              <button
                type="button"
                className="list-row"
                aria-expanded={node.expanded}
                onClick={() => onExpand(node.id, false)}
              >
                <Cover name={node.name} round />
                <span className="list-row__body">
                  <span className="list-row__title">
                    <bdi>{node.name}</bdi>
                  </span>
                  <span className="list-row__subtitle">
                    {t('connection.evidenceCount', {count: edge.evidenceCount})}
                    {' · '}
                    {t(`category.${dominantCategory(edge.kinds)}`)}
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

/** One connection in the panel: who, how many credits, what kind. */
function ConnectionRow({
  node,
  edge,
  onSelect,
  onHint,
}: {
  node: WebNode;
  edge: WebEdge;
  onSelect: () => void;
  onHint: (id: string | null) => void;
}) {
  const {t} = useI18n();
  return (
    <li>
      <button
        type="button"
        className="list-row"
        onClick={onSelect}
        onPointerEnter={() => onHint(node.id)}
        onPointerLeave={() => onHint(null)}
        onFocus={() => onHint(node.id)}
        onBlur={() => onHint(null)}
      >
        <Cover name={node.name} round />
        <span className="list-row__body">
          <span className="list-row__title">
            <bdi>{node.name}</bdi>
          </span>
          <span className="list-row__subtitle">
            <Swatch category={dominantCategory(edge.kinds)} />
            {t('connection.evidenceCount', {count: edge.evidenceCount})}
            {' · '}
            {t(`category.${dominantCategory(edge.kinds)}`)}
          </span>
        </span>
        <Icon name="chevron" size={20} />
      </button>
    </li>
  );
}

export default function ExploreScreen() {
  const {t} = useI18n();
  const {id} = useParams();
  const center = useArtist(id);
  const queryClient = useQueryClient();
  const [state, dispatch] = useReducer(graphReducer, emptyGraph);
  const [categories, setCategories] = useState<ConnectionCategory[]>([
    ...DEFAULT_CATEGORIES,
  ]);
  const [genreFilter, setGenreFilter] =
    useState<GenreSelection>(NO_GENRE_FILTER);
  const [minCredits, setMinCredits] = useState<number>(1);
  const [view, setView] = useState<'web' | 'list'>('web');
  const [selection, setSelection] = useState<Selection>(null);
  const [hint, setHint] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [attempt, setAttempt] = useState(0);
  const [showFilters, setShowFilters] = useState(false);
  const [showLegend, setShowLegend] = useState(false);
  const [loading, setLoading] = useState(true);
  const web = useRef<ConnectionWebHandle>(null);
  usePageTitle(
    center.data
      ? `${t('explore.title')}: ${center.data.displayName}`
      : t('explore.title'),
  );

  const params = useMemo(
    () => ({categories, ...genreFilter}),
    [categories, genreFilter],
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
    setSelection(null);
    setLoading(true);
    load(idOf(artist.name))
      .then(page => active && dispatch({type: 'start', center: artist, page}))
      .catch((e: unknown) => active && setError(e))
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, [center.data, load, attempt]);

  const select = useCallback((next: Selection) => {
    setSelection(next);
    setShowAll(false);
    setHint(null);
  }, []);

  const [opening, setOpening] = useState<string | null>(null);
  const expand = useCallback(
    (nodeId: string, more: boolean) => {
      const token = more ? (state.expansions[nodeId]?.nextPageToken ?? '') : '';
      if (!more && state.nodes[nodeId]?.expanded) {
        select({kind: 'node', id: nodeId});
        return;
      }
      setOpening(nodeId);
      load(nodeId, token)
        .then(page =>
          dispatch({type: 'expand', id: nodeId, page, append: more}),
        )
        .catch((e: unknown) => setError(e))
        .finally(() => setOpening(null));
    },
    [load, select, state.expansions, state.nodes],
  );

  const selectedId = selection?.kind === 'node' ? selection.id : null;

  /** Expands the strongest unexpanded neighbors of the selected artist (or the center). */
  const [growing, setGrowing] = useState(false);
  const expandStrongest = useCallback(() => {
    const from = selectedId ?? state.centerId;
    if (!from || growing) return;
    const targets = strongestUnexpanded(state, from, EXPAND_STRONGEST);
    setGrowing(true);
    // One at a time, so each expansion is its own undo step and the web grows in order.
    void targets
      .reduce<Promise<void>>(
        (chain, nodeId) =>
          chain.then(() =>
            load(nodeId, '').then(page =>
              dispatch({type: 'expand', id: nodeId, page, append: false}),
            ),
          ),
        Promise.resolve(),
      )
      .catch((e: unknown) => setError(e))
      .finally(() => setGrowing(false));
  }, [growing, load, selectedId, state]);

  // What is drawn: connections with enough credits, and the artists they reach.
  const {nodes, edges} = useMemo(() => {
    const allEdges = Object.values(state.edges);
    if (minCredits <= 1)
      return {nodes: Object.values(state.nodes), edges: allEdges};
    const kept = allEdges.filter(edge => edge.evidenceCount >= minCredits);
    const reached = new Set<string>(state.centerId ? [state.centerId] : []);
    for (const edge of kept) {
      reached.add(edge.a);
      reached.add(edge.b);
    }
    return {
      nodes: Object.values(state.nodes).filter(node => reached.has(node.id)),
      edges: kept,
    };
  }, [minCredits, state.centerId, state.edges, state.nodes]);

  /** The web as filtered, for the views that read the graph state directly. */
  const shown = useMemo<GraphState>(
    () =>
      minCredits <= 1
        ? state
        : {
            ...state,
            nodes: Object.fromEntries(nodes.map(node => [node.id, node])),
            edges: Object.fromEntries(edges.map(edge => [edge.key, edge])),
          },
    [edges, minCredits, nodes, state],
  );

  // A selection can outlive what it points to (undo, filters): drop it then.
  const visible = useMemo(() => new Set(nodes.map(n => n.id)), [nodes]);
  useEffect(() => {
    if (!selection) return;
    const gone =
      selection.kind === 'node'
        ? !visible.has(selection.id)
        : !visible.has(selection.a) || !visible.has(selection.b);
    if (gone) setSelection(null);
  }, [selection, visible]);

  const usedCategories = useMemo(() => {
    const present = new Set(edges.map(edge => dominantCategory(edge.kinds)));
    return CATEGORIES.filter(category => present.has(category));
  }, [edges]);

  const describeNode = useCallback(
    (node: WebNode) =>
      node.expanded
        ? t('explore.tip.opened', {name: node.name})
        : t('explore.tip.closed', {name: node.name}),
    [t],
  );
  const describeEdge = useCallback(
    (edge: WebEdge, a: WebNode, b: WebNode) =>
      t('explore.tip.edge', {
        a: a.name,
        b: b.name,
        count: edge.evidenceCount,
        category: t(`category.${dominantCategory(edge.kinds)}`),
      }),
    [t],
  );

  if (center.isPending) return <Spinner />;
  if (center.isError)
    return (
      <div className="web-error">
        <ErrorState
          error={center.error}
          onRetry={() => void center.refetch()}
        />
      </div>
    );

  const centerId = state.centerId;
  const centerName = center.data.displayName;
  const focusId = selectedId ?? centerId;
  const focusNode = focusId ? state.nodes[focusId] : undefined;
  const focusExpansion = focusId ? state.expansions[focusId] : undefined;
  const focusNeighbors = focusId ? neighborsOf(shown, focusId) : [];
  const linkToCenter =
    selectedId && centerId && selectedId !== centerId
      ? state.edges[edgeKey(selectedId, centerId)]
      : undefined;
  const filtersActive =
    minCredits > 1 ||
    genreFilter.genres.length > 0 ||
    categories.length !== DEFAULT_CATEGORIES.length ||
    categories.some(c => !DEFAULT_CATEGORIES.includes(c));
  const empty = Boolean(centerId) && edges.length === 0 && !error && !loading;

  return (
    <div className="web" data-view={view} data-selected={selection !== null}>
      <div className="web__stage">
        {view === 'web' ? (
          <ConnectionWeb
            ref={web}
            nodes={nodes}
            edges={edges}
            centerId={centerId}
            selectedId={selectedId}
            selectedEdge={
              selection?.kind === 'edge'
                ? edgeKey(selection.a, selection.b)
                : null
            }
            hintId={hint}
            label={t('explore.canvasLabel', {name: centerName})}
            describeNode={describeNode}
            describeEdge={describeEdge}
            onSelectNode={nodeId =>
              select(nodeId ? {kind: 'node', id: nodeId} : null)
            }
            onSelectEdge={(a, b) => select({kind: 'edge', a, b})}
            onOpenNode={nodeId => expand(nodeId, false)}
          />
        ) : (
          <div className="web-list">
            <ListView
              state={shown}
              onExpand={expand}
              onShowEvidence={(a, b) => select({kind: 'edge', a, b})}
            />
          </div>
        )}

        <div className="web__top">
          <div className="web__top-row">
            <div className="web__heading">
              <p className="strapline">{t('explore.strapline')}</p>
              <h1>
                <bdi>{centerName}</bdi>
              </h1>
              <p className="web__stats">
                {t('explore.stats', {
                  artists: nodes.length,
                  connections: edges.length,
                })}
              </p>
            </div>
            <div className="web__tools">
              <div
                className="web__bar"
                role="toolbar"
                aria-label={t('explore.tools')}
              >
                <button
                  type="button"
                  className="btn btn--compact btn--text"
                  disabled={state.past.length === 0}
                  onClick={() => dispatch({type: 'undo'})}
                >
                  <Icon name="undo" />
                  <span className="web__bar-label">{t('explore.undo')}</span>
                </button>
                <button
                  type="button"
                  className="btn btn--compact btn--text"
                  disabled={
                    growing ||
                    !centerId ||
                    strongestUnexpanded(state, focusId ?? centerId, 1)
                      .length === 0
                  }
                  onClick={expandStrongest}
                >
                  <Icon name="bolt" />
                  <span className="web__bar-label">
                    {t('explore.expandStrongest', {count: EXPAND_STRONGEST})}
                  </span>
                </button>
              </div>
              <div
                className="web__bar"
                role="group"
                aria-label={t('explore.view')}
              >
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
                  className="icon-btn web__filter-toggle"
                  aria-expanded={showFilters}
                  data-active={filtersActive || undefined}
                  onClick={() => setShowFilters(s => !s)}
                >
                  <Icon name="tune" label={t('explore.filters')} />
                </button>
              </div>
            </div>
          </div>
          {state.trail.length > 1 && (
            <nav className="web__trail" aria-label={t('explore.trail')}>
              <ol className="chips chips--scroll">
                {state.trail.map(nodeId => (
                  <li key={nodeId}>
                    <button
                      type="button"
                      className="chip"
                      aria-pressed={selectedId === nodeId}
                      onClick={() => {
                        select({kind: 'node', id: nodeId});
                        web.current?.focus(nodeId);
                      }}
                    >
                      <bdi>{state.nodes[nodeId]?.name ?? nodeId}</bdi>
                    </button>
                  </li>
                ))}
              </ol>
            </nav>
          )}
        </div>

        {showFilters && (
          <div className="web__filters">
            <div className="section__header">
              <h2>{t('explore.filters')}</h2>
              <button
                type="button"
                className="icon-btn"
                onClick={() => setShowFilters(false)}
              >
                <Icon name="close" label={t('action.close')} />
              </button>
            </div>
            <CategoryChips value={categories} onChange={setCategories} />
            <div
              role="group"
              aria-label={t('explore.minCredits')}
              className="stack web__filter-group"
            >
              <span className="muted label">{t('explore.minCredits')}</span>
              <div className="chips">
                {MIN_CREDITS.map(value => (
                  <button
                    key={value}
                    type="button"
                    className="chip"
                    aria-pressed={minCredits === value}
                    onClick={() => setMinCredits(value)}
                  >
                    {value === 1
                      ? t('explore.minCredits.any')
                      : t('explore.minCredits.atLeast', {count: value})}
                  </button>
                ))}
              </div>
            </div>
            <GenreFilter
              selection={genreFilter}
              onChange={change =>
                setGenreFilter(previous => ({...previous, ...change}))
              }
              coverage={genreCoverage(state)}
            />
          </div>
        )}

        <div className="web__notices">
          {Boolean(error) && (
            <div className="web__notice">
              <ErrorState
                error={error}
                onRetry={() => setAttempt(n => n + 1)}
              />
            </div>
          )}
          {empty && (
            <div className="web__notice">
              <EmptyState
                title={t('explore.empty')}
                action={
                  filtersActive ? (
                    <button
                      type="button"
                      className="btn btn--tonal"
                      onClick={() => {
                        setCategories([...DEFAULT_CATEGORIES]);
                        setGenreFilter(NO_GENRE_FILTER);
                        setMinCredits(1);
                      }}
                    >
                      {t('explore.clearFilters')}
                    </button>
                  ) : undefined
                }
              />
            </div>
          )}
          {state.capped > 0 && (
            <p className="banner">
              {t('explore.truncated', {
                shown: Object.keys(state.nodes).length,
                total: Object.keys(state.nodes).length + state.capped,
              })}
            </p>
          )}
        </div>

        {view === 'web' && (
          <>
            <div className="web__legend">
              <button
                type="button"
                className="web__legend-toggle"
                aria-expanded={showLegend}
                onClick={() => setShowLegend(s => !s)}
              >
                <Icon name="info" size={18} />
                {t('explore.howTo')}
              </button>
              {showLegend && (
                <div className="web__legend-body">
                  <p>{t('explore.howTo.artists')}</p>
                  <p>{t('explore.howTo.lines')}</p>
                  <p>{t('explore.howTo.actions')}</p>
                </div>
              )}
              <ul className="web__keys" aria-label={t('explore.legend')}>
                {usedCategories.map(category => (
                  <li key={category}>
                    <Swatch category={category} />
                    {t(`category.${category}`)}
                  </li>
                ))}
              </ul>
            </div>
            <div
              className="web__zoom"
              role="group"
              aria-label={t('explore.camera')}
            >
              <button
                type="button"
                className="icon-btn"
                onClick={() => web.current?.zoomBy(1.4)}
              >
                <Icon name="add" label={t('explore.zoomIn')} />
              </button>
              <button
                type="button"
                className="icon-btn"
                onClick={() => web.current?.zoomBy(1 / 1.4)}
              >
                <Icon name="remove" label={t('explore.zoomOut')} />
              </button>
              <button
                type="button"
                className="icon-btn"
                onClick={() => web.current?.fit()}
              >
                <Icon name="fit" label={t('explore.fit')} />
              </button>
            </div>
          </>
        )}
      </div>

      <aside className="web__panel" aria-label={t('explore.details')}>
        {selection?.kind === 'edge' ? (
          <EdgePanel
            a={selection.a}
            b={selection.b}
            nameA={state.nodes[selection.a]?.name ?? ''}
            nameB={state.nodes[selection.b]?.name ?? ''}
            categories={categories}
            onClose={() => select(null)}
            onPick={nodeId => {
              select({kind: 'node', id: nodeId});
              web.current?.focus(nodeId);
            }}
          />
        ) : focusNode ? (
          <div className="web-panel">
            <header className="web-panel__header">
              <Cover name={focusNode.name} round />
              <div className="web-panel__titles">
                <p className="strapline">
                  {focusId === centerId
                    ? t('explore.panel.center')
                    : t('search.type.ARTIST')}
                </p>
                <h2>
                  <bdi>{focusNode.name}</bdi>
                </h2>
              </div>
              {selection && (
                <button
                  type="button"
                  className="icon-btn"
                  onClick={() => select(null)}
                >
                  <Icon name="close" label={t('action.close')} />
                </button>
              )}
            </header>

            {linkToCenter && (
              <button
                type="button"
                className="web-panel__link"
                onClick={() =>
                  select({kind: 'edge', a: centerId!, b: selectedId!})
                }
              >
                <Swatch category={dominantCategory(linkToCenter.kinds)} />
                <span>
                  {t('explore.panel.linkedTo', {
                    name: centerName,
                    count: linkToCenter.evidenceCount,
                  })}
                </span>
                <Icon name="chevron" size={20} />
              </button>
            )}

            <div className="web-panel__actions">
              {!focusNode.expanded ? (
                <button
                  type="button"
                  className="btn btn--filled"
                  disabled={opening === focusNode.id}
                  onClick={() => expand(focusNode.id, false)}
                >
                  <Icon name="add" />
                  {t('explore.panel.open')}
                </button>
              ) : (
                focusExpansion?.nextPageToken && (
                  <button
                    type="button"
                    className="btn btn--filled"
                    disabled={opening === focusNode.id}
                    onClick={() => expand(focusNode.id, true)}
                  >
                    <Icon name="add" />
                    {t('explore.panel.more')}
                  </button>
                )
              )}
              <Link className="btn btn--tonal" to={`/artist/${focusNode.id}`}>
                {t('explore.panel.artistPage')}
              </Link>
              {focusId !== centerId && (
                <>
                  <Link
                    className="btn btn--tonal"
                    to={`/explore/${focusNode.id}`}
                  >
                    {t('explore.panel.recenter')}
                  </Link>
                  {!linkToCenter && (
                    <Link
                      className="btn btn--tonal"
                      to={`/six-degrees?from=${centerId}&to=${focusNode.id}`}
                    >
                      {t('explore.panel.path', {name: centerName})}
                    </Link>
                  )}
                </>
              )}
            </div>

            {focusExpansion && (
              <p className="web-panel__note">
                {t('explore.panel.inData', {
                  shown: focusExpansion.shown,
                  total: focusExpansion.total,
                })}
              </p>
            )}

            {focusNeighbors.length > 0 && (
              <section className="web-panel__section">
                <h3>
                  {focusNode.expanded
                    ? t('explore.panel.strongest')
                    : t('explore.panel.inWeb')}
                </h3>
                <ul className="list">
                  {(showAll
                    ? focusNeighbors
                    : focusNeighbors.slice(0, PANEL_ROWS)
                  ).map(({node, edge}) => (
                    <ConnectionRow
                      key={node.id}
                      node={node}
                      edge={edge}
                      onHint={setHint}
                      onSelect={() =>
                        select({kind: 'edge', a: focusNode.id, b: node.id})
                      }
                    />
                  ))}
                </ul>
                {!showAll && focusNeighbors.length > PANEL_ROWS && (
                  <button
                    type="button"
                    className="btn btn--text"
                    onClick={() => setShowAll(true)}
                  >
                    {t('explore.panel.showAll', {
                      count: focusNeighbors.length,
                    })}
                  </button>
                )}
              </section>
            )}

            {!selection && (
              <p className="web-panel__hint">{t('explore.panel.hint')}</p>
            )}
          </div>
        ) : (
          <Spinner />
        )}
      </aside>
    </div>
  );
}

/** Why two artists are linked: every credit, each with its source. */
function EdgePanel({
  a,
  b,
  nameA,
  nameB,
  categories,
  onClose,
  onPick,
}: {
  a: string;
  b: string;
  nameA: string;
  nameB: string;
  categories: ConnectionCategory[];
  onClose: () => void;
  onPick: (id: string) => void;
}) {
  const {t} = useI18n();
  return (
    <div className="web-panel">
      <header className="web-panel__header">
        <span className="web-panel__pair" aria-hidden="true">
          <Cover name={nameA} round />
          <Cover name={nameB} round />
        </span>
        <div className="web-panel__titles">
          <p className="strapline">{t('explore.panel.connection')}</p>
          <h2>
            <button
              type="button"
              className="web-panel__name"
              onClick={() => onPick(a)}
            >
              <bdi>{nameA}</bdi>
            </button>
            <span aria-hidden="true"> · </span>
            <button
              type="button"
              className="web-panel__name"
              onClick={() => onPick(b)}
            >
              <bdi>{nameB}</bdi>
            </button>
          </h2>
        </div>
        <button type="button" className="icon-btn" onClick={onClose}>
          <Icon name="close" label={t('action.close')} />
        </button>
      </header>
      <ConnectionEvidence a={a} b={b} categories={categories} />
    </div>
  );
}
