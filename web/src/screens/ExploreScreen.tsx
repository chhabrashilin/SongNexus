/**
 * The connection web (S1, US-02/06): start from an artist, open their
 * connections, select a line for the credits behind it.
 *
 * The page is the web: the canvas fills it, glass tools float over it, and a
 * details panel answers "who is this?" and "why are they linked?" without
 * leaving (beside the web on wide screens, a bottom sheet on phones). The list
 * view carries the same content for keyboard and screen-reader users (AC-2.3).
 */
import {useQueryClient} from '@tanstack/react-query';
import {
  useCallback,
  useEffect,
  useMemo,
  useReducer,
  useRef,
  useState,
  type CSSProperties,
} from 'react';
import {Link, useNavigate, useParams} from 'react-router';

import {ApiError, idOf} from '../api/client';
import {
  fetchConnections,
  useArtist,
  type ConnectionCategory,
} from '../api/queries';
import {useAmbient} from '../app/ambient';
import {NO_GENRE_FILTER, type GenreSelection} from '../app/genreSelection';
import {usePageTitle} from '../app/Shell';
import {useStarterArtists} from '../app/starters';
import {Avatar, imageOf} from '../components/ArtistRow';
import {ConnectionEvidence} from '../components/ConnectionSheet';
import {
  CATEGORIES,
  CATEGORY_ENCODING,
  DEFAULT_CATEGORIES,
  dominantCategory,
} from '../components/encoding';
import {CategoryChips, GenreFilter, Swatch} from '../components/Filters';
import {Icon} from '../components/Icon';
import {SearchBox} from '../components/SearchBox';
import {Cover, hueOf} from '../components/Shelf';
import {useSnackbar} from '../components/Snackbar';
import {EmptyState, ErrorState} from '../components/States';
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
  orbitOf,
  ORBITS,
  type GraphState,
  type Orbit,
  type WebEdge,
  type WebNode,
  type WebSong,
} from '../explore/graphState';
import {ListenLink, Moment, Portrait, youTubeMusicUrl} from '../explore/parts';
import {useI18n} from '../i18n/i18n';

const FIRST_PAGE = 25;
/** How many artists "expand the strongest" opens at once. */
const EXPAND_STRONGEST = 5;
/** "Only show connections with at least this many credits." */
const MIN_CREDITS = [1, 3, 10] as const;
/** Rows shown in the panel before "show all". */
const PANEL_ROWS = 6;
/** A downward swipe on the sheet's handle longer than this closes it. */
const SWIPE_CLOSE_PX = 56;
/** The web lists the people a listener is likely to know first (server ranking). */
const ORDER = 'relevance desc';
/** Remembers that the first-visit hint was dismissed (this browser only). */
const HINT_KEY = 'songnexus.webHint';
/** Each orbit drawn with the line color of its kind of connection. */
const ORBIT_CATEGORY: Record<Orbit, ConnectionCategory> = {
  FEATURES: 'FEATURES',
  PRODUCTION: 'PRODUCERS',
  CREDITS: 'CONTRIBUTIONS',
};

/** "24.7K": listener counts read at a glance. */
function useCompact(): (value: number) => string {
  const {locale} = useI18n();
  return useMemo(() => {
    const format = new Intl.NumberFormat(locale, {
      notation: 'compact',
      maximumFractionDigits: 1,
    });
    return (value: number) => format.format(value);
  }, [locale]);
}

function readHintSeen(): boolean {
  try {
    return localStorage.getItem(HINT_KEY) === 'seen';
  } catch {
    return true;
  }
}

/** The songs two artists made together, each a page and a "play" link out. */
function SongList({songs, artist}: {songs: WebSong[]; artist: string}) {
  const {t} = useI18n();
  return (
    <ul className="web-songs">
      {songs.map(song => (
        <li key={song.id} className="web-song">
          <Link className="web-song__link" to={`/song/${song.id}`}>
            <span
              className="web-song__art"
              style={{'--hue': hueOf(song.title)} as CSSProperties}
              aria-hidden="true"
            >
              <Icon name="note" size={18} />
            </span>
            <span className="web-song__title">
              <bdi>{song.title}</bdi>
            </span>
          </Link>
          <a
            className="icon-btn web-song__play"
            href={youTubeMusicUrl(`${song.title} ${artist}`)}
            target="_blank"
            rel="noopener noreferrer"
          >
            <Icon
              name="play"
              label={t('explore.song.play', {title: song.title})}
            />
          </a>
        </li>
      ))}
    </ul>
  );
}

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
                <Avatar name={node.name} image={node.image} />
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

/** One connection in the panel: who, how many credits, what kind, how strong. */
function ConnectionRow({
  node,
  edge,
  strongest,
  onSelect,
  onHint,
}: {
  node: WebNode;
  edge: WebEdge;
  /** The strongest connection in the list, to scale the strength bar. */
  strongest: number;
  onSelect: () => void;
  onHint: (id: string | null) => void;
}) {
  const {t} = useI18n();
  const category = dominantCategory(edge.kinds);
  return (
    <li>
      <button
        type="button"
        className="list-row web-row"
        onClick={onSelect}
        onPointerEnter={() => onHint(node.id)}
        onPointerLeave={() => onHint(null)}
        onFocus={() => onHint(node.id)}
        onBlur={() => onHint(null)}
      >
        <Avatar name={node.name} image={node.image} />
        <span className="list-row__body">
          <span className="list-row__title">
            <bdi>{node.name}</bdi>
          </span>
          <span className="list-row__subtitle">
            <Swatch category={category} />
            {edge.songs[0] ? (
              <bdi>
                {t('explore.row.song', {
                  song: edge.songs[0].title,
                  count: edge.evidenceCount,
                })}
              </bdi>
            ) : (
              <>
                {t('connection.evidenceCount', {count: edge.evidenceCount})}
                {' · '}
                {t(`category.${category}`)}
              </>
            )}
          </span>
          <span className="web-row__bar" aria-hidden="true">
            <span
              style={
                {
                  inlineSize: `${Math.max(6, (100 * edge.strength) / (strongest || 1))}%`,
                  '--bar': CATEGORY_ENCODING[category].color,
                } as CSSProperties
              }
            />
          </span>
        </span>
        <Icon name="chevron" size={20} />
      </button>
    </li>
  );
}

/** The page's layout while the artist loads: the same shapes, shimmering. */
function WebSkeleton() {
  const {t} = useI18n();
  return (
    <div className="web" data-loading="true">
      <div className="web__stage">
        <div className="web-skeleton" aria-hidden="true">
          <span className="web-skeleton__core skeleton" />
          {Array.from({length: 9}, (_, i) => (
            <span
              key={i}
              className="web-skeleton__orbit skeleton"
              style={{'--i': i} as CSSProperties}
            />
          ))}
        </div>
        <div className="web__top">
          <div className="web__heading">
            <span className="skeleton web-skeleton__line" data-w="s" />
            <span className="skeleton web-skeleton__line" data-w="l" />
          </div>
        </div>
        <p className="visually-hidden" role="status">
          {t('state.loading')}
        </p>
      </div>
      <aside className="web__panel" aria-hidden="true">
        <div className="web-panel">
          <span className="skeleton web-skeleton__portrait" />
          <span className="skeleton web-skeleton__line" data-w="l" />
          <span className="skeleton web-skeleton__line" data-w="m" />
          {Array.from({length: 5}, (_, i) => (
            <span key={i} className="skeleton web-skeleton__row" />
          ))}
        </div>
      </aside>
    </div>
  );
}

/** The artist isn't in our data (yet): say so, and offer ways on. */
function NotInData() {
  const {t} = useI18n();
  const navigate = useNavigate();
  const starters = useStarterArtists();
  return (
    <div className="web-missing">
      <Moment
        icon="explore"
        title={t('explore.missing.title')}
        body={t('explore.missing.body')}
      >
        <div className="web-missing__search">
          <SearchBox
            label={t('explore.hub.web.search')}
            placeholder={t('explore.hub.web.search')}
            types={['ARTIST']}
            onPick={result => void navigate(`/explore/${idOf(result.name)}`)}
          />
        </div>
        {starters.length > 0 && (
          <ul className="web-missing__picks">
            {starters.slice(0, 6).map(artist => (
              <li key={artist.name}>
                <Link
                  className="pill-pick"
                  to={`/explore/${idOf(artist.name)}`}
                >
                  <Cover
                    name={artist.displayName}
                    image={imageOf(artist)}
                    round
                  />
                  <bdi>{artist.displayName}</bdi>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </Moment>
    </div>
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
  const [orbit, setOrbit] = useState<Orbit | null>(null);
  const [hintSeen, setHintSeen] = useState(readHintSeen);
  const [sharing, setSharing] = useState(false);
  const snackbar = useSnackbar();
  const compact = useCompact();
  const web = useRef<ConnectionWebHandle>(null);
  const swipe = useRef<number | null>(null);
  usePageTitle(
    center.data
      ? `${t('explore.title')}: ${center.data.displayName}`
      : t('explore.title'),
  );
  useAmbient(center.data?.displayName ?? null);

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
          {...params, pageSize: FIRST_PAGE, pageToken, orderBy: ORDER},
        ],
        queryFn: () =>
          fetchConnections(artistId, {
            ...params,
            pageSize: FIRST_PAGE,
            pageToken,
            orderBy: ORDER,
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
    if (minCredits <= 1 && !orbit)
      return {nodes: Object.values(state.nodes), edges: allEdges};
    const kept = allEdges.filter(
      edge =>
        edge.evidenceCount >= minCredits &&
        (!orbit || orbitOf(edge.kinds) === orbit),
    );
    const reached = new Set<string>(state.centerId ? [state.centerId] : []);
    for (const edge of kept) {
      reached.add(edge.a);
      reached.add(edge.b);
    }
    return {
      nodes: Object.values(state.nodes).filter(node => reached.has(node.id)),
      edges: kept,
    };
  }, [minCredits, orbit, state.centerId, state.edges, state.nodes]);

  /** The web as filtered, for the views that read the graph state directly. */
  const shown = useMemo<GraphState>(
    () =>
      minCredits <= 1 && !orbit
        ? state
        : {
            ...state,
            nodes: Object.fromEntries(nodes.map(node => [node.id, node])),
            edges: Object.fromEntries(edges.map(edge => [edge.key, edge])),
          },
    [edges, minCredits, nodes, orbit, state],
  );

  /** How many of the start's connections sit on each orbit (before the orbit filter). */
  const orbitCounts = useMemo(() => {
    const counts: Record<Orbit, number> = {
      FEATURES: 0,
      PRODUCTION: 0,
      CREDITS: 0,
    };
    for (const edge of Object.values(state.edges))
      if (edge.a === state.centerId || edge.b === state.centerId)
        counts[orbitOf(edge.kinds)]++;
    return counts;
  }, [state.centerId, state.edges]);

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
    (node: WebNode) => {
      const name = node.listeners
        ? t('explore.tip.reach', {
            name: node.name,
            listeners: compact(node.listeners),
          })
        : node.name;
      return node.expanded
        ? t('explore.tip.opened', {name})
        : t('explore.tip.closed', {name});
    },
    [compact, t],
  );
  const describeEdge = useCallback(
    (edge: WebEdge, a: WebNode, b: WebNode) =>
      edge.songs[0]
        ? t('explore.tip.song', {
            a: a.name,
            b: b.name,
            song: edge.songs[0].title,
            more: edge.evidenceCount - 1,
          })
        : t('explore.tip.edge', {
            a: a.name,
            b: b.name,
            count: edge.evidenceCount,
            category: t(`category.${dominantCategory(edge.kinds)}`),
          }),
    [t],
  );
  const describeOrbit = useCallback(
    (which: Orbit, count: number) =>
      t('explore.orbit.label', {orbit: t(`explore.orbit.${which}`), count}),
    [t],
  );

  const dismissHint = useCallback(() => {
    setHintSeen(true);
    try {
      localStorage.setItem(HINT_KEY, 'seen');
    } catch {
      // Storage unavailable: the hint stays dismissed for this visit.
    }
  }, []);

  /** The web as a story image: the system share sheet, or a download. */
  const share = useCallback(
    async (name: string) => {
      if (!web.current || sharing) return;
      setSharing(true);
      try {
        const blob = await web.current.snapshot({
          title: name,
          subtitle: t('explore.share.subtitle'),
          brand: t('app.name'),
        });
        if (!blob) {
          snackbar(t('explore.share.failed'));
          return;
        }
        const slug = name.replace(/[^\p{L}\p{N}]+/gu, '-').toLowerCase();
        const file = new File([blob], `${slug}-songnexus.png`, {
          type: 'image/png',
        });
        if (navigator.canShare?.({files: [file]})) {
          await navigator.share({
            files: [file],
            title: t('explore.share.title', {name}),
          });
          return;
        }
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = file.name;
        link.click();
        setTimeout(() => URL.revokeObjectURL(url), 10_000);
        snackbar(t('explore.share.saved'));
      } catch (e: unknown) {
        // Closing the share sheet is not a failure.
        if (!(e instanceof DOMException && e.name === 'AbortError'))
          snackbar(t('explore.share.failed'));
      } finally {
        setSharing(false);
      }
    },
    [sharing, snackbar, t],
  );

  if (center.isPending) return <WebSkeleton />;
  if (center.isError)
    return center.error instanceof ApiError &&
      center.error.status === 'NOT_FOUND' ? (
      <NotInData />
    ) : (
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
  const filtersActive =
    orbit !== null ||
    minCredits > 1 ||
    genreFilter.genres.length > 0 ||
    categories.length !== DEFAULT_CATEGORIES.length ||
    categories.some(c => !DEFAULT_CATEGORIES.includes(c));
  const empty = Boolean(centerId) && edges.length === 0 && !error && !loading;
  const drawing = loading && edges.length === 0 && !error;

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
            keyHelp={t('explore.keys')}
            describeNode={describeNode}
            describeEdge={describeEdge}
            describeOrbit={describeOrbit}
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
                className="web__bar glass"
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
                <button
                  type="button"
                  className="btn btn--compact btn--text"
                  disabled={!centerId || view !== 'web' || sharing}
                  onClick={() => void share(centerName)}
                >
                  <Icon name="share" />
                  <span className="web__bar-label">{t('explore.share')}</span>
                </button>
              </div>
              <div
                className="web__bar glass"
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
                {state.trail.map(nodeId => {
                  const node = state.nodes[nodeId];
                  return (
                    <li key={nodeId}>
                      <button
                        type="button"
                        className="chip web__crumb"
                        aria-pressed={selectedId === nodeId}
                        onClick={() => {
                          select({kind: 'node', id: nodeId});
                          web.current?.focus(nodeId);
                        }}
                      >
                        <Cover
                          name={node?.name ?? nodeId}
                          image={node?.image}
                          round
                        />
                        <bdi>{node?.name ?? nodeId}</bdi>
                      </button>
                    </li>
                  );
                })}
              </ol>
            </nav>
          )}
        </div>

        {showFilters && (
          <div className="web__filters glass">
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
          {drawing && view === 'web' && (
            <p className="web__drawing glass" role="status">
              <span className="web__drawing-dot" aria-hidden="true" />
              {t('explore.drawing', {name: centerName})}
            </p>
          )}
          {Boolean(error) && (
            <div className="web__notice glass">
              <ErrorState
                error={error}
                onRetry={() => setAttempt(n => n + 1)}
              />
            </div>
          )}
          {empty && (
            <div className="web__notice glass">
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
                        setOrbit(null);
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
            <div className="web__legend glass">
              {/* The first-visit hint lives in the legend, never over the web. */}
              {!hintSeen && !drawing && edges.length > 0 && (
                <div className="web__coach" role="note">
                  <Icon name="spark" size={18} />
                  <p>{t('explore.coach')}</p>
                  <button
                    type="button"
                    className="icon-btn"
                    onClick={dismissHint}
                  >
                    <Icon name="close" label={t('explore.coach.dismiss')} />
                  </button>
                </div>
              )}
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
                  <p>{t('explore.keys')}</p>
                </div>
              )}
              <div
                className="web__orbits chips chips--scroll"
                role="group"
                aria-label={t('explore.legend')}
              >
                <button
                  type="button"
                  className="chip"
                  aria-pressed={orbit === null}
                  onClick={() => setOrbit(null)}
                >
                  {t('explore.orbit.all')}
                </button>
                {ORBITS.filter(o => orbitCounts[o] > 0).map(o => (
                  <button
                    key={o}
                    type="button"
                    className="chip"
                    aria-pressed={orbit === o}
                    onClick={() => setOrbit(orbit === o ? null : o)}
                  >
                    <Swatch category={ORBIT_CATEGORY[o]} />
                    {t(`explore.orbit.${o}`)}
                    <span className="web__orbit-count">{orbitCounts[o]}</span>
                  </button>
                ))}
              </div>
              {usedCategories.some(
                c => !Object.values(ORBIT_CATEGORY).includes(c),
              ) && (
                <ul className="web__keys" aria-label={t('explore.otherLines')}>
                  {usedCategories
                    .filter(c => !Object.values(ORBIT_CATEGORY).includes(c))
                    .map(category => (
                      <li key={category}>
                        <Swatch category={category} />
                        {t(`category.${category}`)}
                      </li>
                    ))}
                </ul>
              )}
            </div>
            <div
              className="web__zoom glass"
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
        {selection && (
          <button
            type="button"
            className="web__grabber"
            onClick={() => select(null)}
            onPointerDown={event => {
              swipe.current = event.clientY;
            }}
            onPointerUp={event => {
              const start = swipe.current;
              swipe.current = null;
              if (start !== null && event.clientY - start > SWIPE_CLOSE_PX)
                select(null);
            }}
          >
            <span className="visually-hidden">{t('explore.panel.hide')}</span>
          </button>
        )}
        {selection?.kind === 'edge' ? (
          <EdgePanel
            a={state.nodes[selection.a]}
            b={state.nodes[selection.b]}
            edge={state.edges[edgeKey(selection.a, selection.b)]}
            categories={categories}
            onClose={() => select(null)}
            onPick={nodeId => {
              select({kind: 'node', id: nodeId});
              web.current?.focus(nodeId);
            }}
          />
        ) : focusNode && centerId ? (
          <ArtistPanel
            node={focusNode}
            state={state}
            shown={shown}
            centerId={centerId}
            centerName={centerName}
            categories={categories}
            selected={selection !== null}
            showAll={showAll}
            opening={opening === focusNode.id}
            onShowAll={() => setShowAll(true)}
            onExpand={more => expand(focusNode.id, more)}
            onClose={() => select(null)}
            onHint={setHint}
            onSelectEdge={(a, b) => select({kind: 'edge', a, b})}
          />
        ) : (
          <div className="web-panel" aria-hidden="true">
            <span className="skeleton web-skeleton__portrait" />
            <span className="skeleton web-skeleton__line" data-w="l" />
            <span className="skeleton web-skeleton__line" data-w="m" />
          </div>
        )}
      </aside>
    </div>
  );
}

/** Who an artist is, how they link to the start, and their strongest connections. */
function ArtistPanel({
  node,
  state,
  shown,
  centerId,
  centerName,
  categories,
  selected,
  showAll,
  opening,
  onShowAll,
  onExpand,
  onClose,
  onHint,
  onSelectEdge,
}: {
  node: WebNode;
  state: GraphState;
  shown: GraphState;
  centerId: string;
  centerName: string;
  categories: ConnectionCategory[];
  selected: boolean;
  showAll: boolean;
  opening: boolean;
  onShowAll: () => void;
  onExpand: (more: boolean) => void;
  onClose: () => void;
  onHint: (id: string | null) => void;
  onSelectEdge: (a: string, b: string) => void;
}) {
  const {t} = useI18n();
  const artist = useArtist(node.id);
  const isCenter = node.id === centerId;
  const expansion = state.expansions[node.id];
  const neighbors = neighborsOf(shown, node.id);
  const strongest = neighbors[0]?.edge.strength ?? 1;
  const linkToCenter = !isCenter
    ? state.edges[edgeKey(node.id, centerId)]
    : undefined;
  const image = node.image ?? imageOf(artist.data);
  const total = artist.data?.connectionCount ?? expansion?.total;
  const compact = useCompact();
  const genres = artist.data?.genres.slice(0, 3) ?? [];

  return (
    <div
      className="web-panel"
      style={{'--hue': hueOf(node.name)} as CSSProperties}
    >
      <header className="web-panel__hero">
        <Portrait name={node.name} image={image} size="l" eager />
        <div className="web-panel__titles">
          <p className="strapline">
            {isCenter ? t('explore.panel.center') : t('search.type.ARTIST')}
          </p>
          <h2>
            <bdi>{node.name}</bdi>
          </h2>
          {artist.data?.disambiguation && (
            <p className="web-panel__dis">{artist.data.disambiguation}</p>
          )}
        </div>
        {selected && (
          <button
            type="button"
            className="icon-btn web-panel__close"
            onClick={onClose}
          >
            <Icon name="close" label={t('action.close')} />
          </button>
        )}
      </header>

      <dl className="web-panel__stats">
        {node.listeners !== null && (
          <div>
            <dt>{t('explore.panel.stat.listeners')}</dt>
            <dd>{compact(node.listeners)}</dd>
          </div>
        )}
        {total !== undefined && (
          <div>
            <dt>{t('explore.panel.stat.inData')}</dt>
            <dd>{total}</dd>
          </div>
        )}
        <div>
          <dt>{t('explore.panel.stat.inWeb')}</dt>
          <dd>{neighbors.length}</dd>
        </div>
        {linkToCenter && (
          <div>
            <dt>{t('explore.panel.stat.credits', {name: centerName})}</dt>
            <dd>{linkToCenter.evidenceCount}</dd>
          </div>
        )}
      </dl>

      {genres.length > 0 && (
        <ul className="web-panel__genres">
          {genres.map(genre => (
            <li key={genre.genre}>{genre.displayName}</li>
          ))}
        </ul>
      )}

      <div className="web-panel__actions">
        {!node.expanded ? (
          <button
            type="button"
            className="btn btn--filled"
            disabled={opening}
            onClick={() => onExpand(false)}
          >
            <Icon name="add" />
            {t('explore.panel.open')}
          </button>
        ) : (
          expansion?.nextPageToken && (
            <button
              type="button"
              className="btn btn--filled"
              disabled={opening}
              onClick={() => onExpand(true)}
            >
              <Icon name="add" />
              {t('explore.panel.more')}
            </button>
          )
        )}
        <ListenLink query={node.name} />
        <Link className="btn btn--tonal" to={`/artist/${node.id}`}>
          {t('explore.panel.artistPage')}
        </Link>
        {!isCenter && (
          <>
            <Link className="btn btn--tonal" to={`/explore/${node.id}`}>
              <Icon name="explore" />
              {t('explore.panel.recenter')}
            </Link>
            {!linkToCenter && (
              <Link
                className="btn btn--tonal"
                to={`/six-degrees?from=${centerId}&to=${node.id}`}
              >
                <Icon name="route" />
                {t('explore.panel.path', {name: centerName})}
              </Link>
            )}
          </>
        )}
      </div>

      {linkToCenter && linkToCenter.songs.length > 0 && (
        <section className="web-panel__section">
          <h3>{t('explore.panel.songs', {name: centerName})}</h3>
          <SongList songs={linkToCenter.songs} artist={node.name} />
        </section>
      )}

      {linkToCenter && (
        <section className="web-panel__section">
          <div className="web-panel__section-head">
            <h3>{t('explore.panel.creditsWith', {name: centerName})}</h3>
            <button
              type="button"
              className="btn btn--text btn--compact"
              onClick={() => onSelectEdge(centerId, node.id)}
            >
              <Swatch category={dominantCategory(linkToCenter.kinds)} />
              {t('explore.panel.showConnection')}
            </button>
          </div>
          <ConnectionEvidence
            a={centerId}
            b={node.id}
            categories={categories}
          />
        </section>
      )}

      {neighbors.length > 0 && (
        <section className="web-panel__section">
          <h3>
            {node.expanded
              ? t('explore.panel.strongest')
              : t('explore.panel.inWeb')}
          </h3>
          <ul className="list">
            {(showAll ? neighbors : neighbors.slice(0, PANEL_ROWS)).map(
              ({node: other, edge}) => (
                <ConnectionRow
                  key={other.id}
                  node={other}
                  edge={edge}
                  strongest={strongest}
                  onHint={onHint}
                  onSelect={() => onSelectEdge(node.id, other.id)}
                />
              ),
            )}
          </ul>
          {!showAll && neighbors.length > PANEL_ROWS && (
            <button type="button" className="btn btn--text" onClick={onShowAll}>
              {t('explore.panel.showAll', {count: neighbors.length})}
            </button>
          )}
          {expansion && (
            <p className="web-panel__note">
              {t('explore.panel.inData', {
                shown: expansion.shown,
                total: expansion.total,
              })}
            </p>
          )}
        </section>
      )}

      {!selected && (
        <p className="web-panel__hint">{t('explore.panel.hint')}</p>
      )}
    </div>
  );
}

/** Why two artists are linked: every credit, each with its source. */
function EdgePanel({
  a,
  b,
  edge,
  categories,
  onClose,
  onPick,
}: {
  a: WebNode | undefined;
  b: WebNode | undefined;
  edge: WebEdge | undefined;
  categories: ConnectionCategory[];
  onClose: () => void;
  onPick: (id: string) => void;
}) {
  const {t} = useI18n();
  if (!a || !b) return null;
  return (
    <div className="web-panel">
      <header className="web-panel__hero web-panel__hero--pair">
        <span className="web-panel__pair" aria-hidden="true">
          <Portrait name={a.name} image={a.image} size="m" />
          <Portrait name={b.name} image={b.image} size="m" />
        </span>
        <div className="web-panel__titles">
          <p className="strapline">{t('explore.panel.connection')}</p>
          <h2>
            <button
              type="button"
              className="web-panel__name"
              onClick={() => onPick(a.id)}
            >
              <bdi>{a.name}</bdi>
            </button>
            <span className="web-panel__amp" aria-hidden="true">
              {' & '}
            </span>
            <button
              type="button"
              className="web-panel__name"
              onClick={() => onPick(b.id)}
            >
              <bdi>{b.name}</bdi>
            </button>
          </h2>
        </div>
        <button
          type="button"
          className="icon-btn web-panel__close"
          onClick={onClose}
        >
          <Icon name="close" label={t('action.close')} />
        </button>
      </header>
      {edge && edge.songs.length > 0 && (
        <section className="web-panel__section">
          <h3>{t('explore.panel.songsTogether')}</h3>
          <SongList songs={edge.songs} artist={`${a.name} ${b.name}`} />
        </section>
      )}
      <ConnectionEvidence a={a.id} b={b.id} categories={categories} />
    </div>
  );
}
