/**
 * The connection web, drawn on a canvas (SVG doesn't hold up past ~300 nodes).
 *
 * d3-force lays it out, d3-zoom pans and zooms, d3-drag moves an artist.
 * Artists are drawn as their generated cover (the same art as everywhere else
 * in the app), lines carry the kind of connection (color and dash) and its
 * strength (width). Pointing at something lights up its neighborhood and names
 * it; clicking selects it; double-clicking an artist opens their connections.
 *
 * The canvas is a visual aid: the list view next to it carries the same content
 * for keyboard and screen-reader users (AC-2.3).
 */
import {drag} from 'd3-drag';
import {
  forceCollide,
  forceLink,
  forceManyBody,
  forceSimulation,
  forceX,
  forceY,
  type Simulation,
  type SimulationLinkDatum,
  type SimulationNodeDatum,
} from 'd3-force';
import {pointer, select} from 'd3-selection';
import {
  zoom,
  zoomIdentity,
  type ZoomBehavior,
  type ZoomTransform,
} from 'd3-zoom';
import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useRef,
} from 'react';

import {initialOf} from '../components/ArtistRow';
import {CATEGORY_ENCODING, dominantCategory} from '../components/encoding';
import {hueOf} from '../components/Shelf';

import type {WebEdge, WebNode} from './graphState';

interface SimNode extends SimulationNodeDatum {
  id: string;
  data: WebNode;
  /** Radius in world units. */
  r: number;
  hue: number;
  initial: string;
  /** When the node first appeared (for the fade-in). */
  born: number;
  /** Cached label width at the label font, in CSS pixels. */
  labelWidth: number;
  /** The strongest connection this artist has in the web (label priority). */
  weight: number;
}

interface SimLink extends SimulationLinkDatum<SimNode> {
  data: WebEdge;
}

export interface ConnectionWebHandle {
  fit: () => void;
  zoomBy: (factor: number) => void;
  focus: (id: string) => void;
}

interface Props {
  nodes: WebNode[];
  edges: WebEdge[];
  centerId: string | null;
  selectedId: string | null;
  /** Key of the selected connection (see edgeKey), if one is selected. */
  selectedEdge: string | null;
  /** An artist highlighted from outside the canvas (hovering a list row). */
  hintId?: string | null;
  label: string;
  /** Text for the pointer tooltip. */
  describeNode: (node: WebNode) => string;
  describeEdge: (edge: WebEdge, a: WebNode, b: WebNode) => string;
  onSelectNode: (id: string | null) => void;
  onSelectEdge: (a: string, b: string) => void;
  /** Double-click: open this artist's connections. */
  onOpenNode: (id: string) => void;
}

const CENTER_RADIUS = 24;
const MAX_PIXEL_RATIO = 2;
/** Below this simulation alpha the layout reads as still; full-quality frames return. */
const SETTLED_ALPHA = 0.05;
/** Below this alpha the layout is close enough to frame the camera on it. */
const FRAME_ALPHA = 0.14;
const FADE_MS = 350;
const CAMERA_MS = 450;
const LABEL_FONT = 12;
const MAX_LABELS = 70;
/** Room kept clear of the overlays (title and tools above, legend below). */
const PADDING = {top: 132, right: 36, bottom: 84, left: 36};
const SPRITE_SIZE = 96;
const HUE_STEP = 12;

const lineWidth = (edge: WebEdge) =>
  Math.min(7, 1 + 1.3 * Math.log2(1 + edge.strength));

function radiusOf(node: WebNode, weight: number, isCenter: boolean): number {
  if (isCenter) return CENTER_RADIUS;
  const base = 8 + Math.min(7, 2.4 * Math.log2(1 + weight));
  return node.expanded ? base + 3 : base;
}

/** Resolves CSS custom properties (including light-dark()) to concrete colors. */
function colorResolver(host: HTMLElement): {
  (variable: string): string;
  reset: () => void;
  dispose: () => void;
} {
  const probe = document.createElement('span');
  probe.style.display = 'none';
  host.appendChild(probe);
  const cache = new Map<string, string>();
  const resolve = (variable: string) => {
    let value = cache.get(variable);
    if (value === undefined) {
      probe.style.color = variable.startsWith('var(')
        ? variable
        : `var(${variable})`;
      value = getComputedStyle(probe).color;
      cache.set(variable, value);
    }
    return value;
  };
  resolve.reset = () => cache.clear();
  resolve.dispose = () => probe.remove();
  return resolve;
}

/** The generated cover for a hue, drawn once and reused for every node with it. */
const sprites = new Map<number, HTMLCanvasElement>();
function spriteFor(hue: number): HTMLCanvasElement {
  const bucket = Math.round(hue / HUE_STEP) * HUE_STEP;
  let sprite = sprites.get(bucket);
  if (!sprite) {
    sprite = document.createElement('canvas');
    sprite.width = sprite.height = SPRITE_SIZE;
    const context = sprite.getContext('2d');
    if (context) {
      const half = SPRITE_SIZE / 2;
      context.beginPath();
      context.arc(half, half, half, 0, 2 * Math.PI);
      context.clip();
      const base = context.createLinearGradient(0, 0, SPRITE_SIZE, SPRITE_SIZE);
      base.addColorStop(0, `hsl(${bucket} 62% 44%)`);
      base.addColorStop(1, `hsl(${bucket - 30} 55% 16%)`);
      context.fillStyle = base;
      context.fillRect(0, 0, SPRITE_SIZE, SPRITE_SIZE);
      const light = context.createRadialGradient(
        SPRITE_SIZE * 0.3,
        SPRITE_SIZE * 0.2,
        0,
        SPRITE_SIZE * 0.3,
        SPRITE_SIZE * 0.2,
        SPRITE_SIZE * 0.7,
      );
      light.addColorStop(0, `hsl(${bucket + 35} 85% 64% / 85%)`);
      light.addColorStop(1, `hsl(${bucket + 35} 85% 64% / 0%)`);
      context.fillStyle = light;
      context.fillRect(0, 0, SPRITE_SIZE, SPRITE_SIZE);
    }
    sprites.set(bucket, sprite);
  }
  return sprite;
}

function distanceToSegment(
  px: number,
  py: number,
  ax: number,
  ay: number,
  bx: number,
  by: number,
): number {
  const dx = bx - ax;
  const dy = by - ay;
  const lengthSq = dx * dx + dy * dy || 1;
  const t = Math.max(
    0,
    Math.min(1, ((px - ax) * dx + (py - ay) * dy) / lengthSq),
  );
  return Math.hypot(px - (ax + t * dx), py - (ay + t * dy));
}

type Hit = {kind: 'node'; node: SimNode} | {kind: 'edge'; link: SimLink} | null;

export const ConnectionWeb = forwardRef<ConnectionWebHandle, Props>(
  (
    {
      nodes,
      edges,
      centerId,
      selectedId,
      selectedEdge,
      hintId = null,
      label,
      describeNode,
      describeEdge,
      onSelectNode,
      onSelectEdge,
      onOpenNode,
    },
    ref,
  ) => {
    const canvasRef = useRef<HTMLCanvasElement>(null);
    const tipRef = useRef<HTMLDivElement>(null);
    const simRef = useRef<Simulation<SimNode, SimLink> | null>(null);
    const simNodes = useRef(new Map<string, SimNode>());
    const simLinks = useRef<SimLink[]>([]);
    const neighbors = useRef(new Map<string, Set<string>>());
    const transform = useRef<ZoomTransform>(zoomIdentity);
    const zoomRef = useRef<ZoomBehavior<HTMLCanvasElement, unknown> | null>(
      null,
    );
    const colorOf = useRef<ReturnType<typeof colorResolver> | null>(null);
    const frame = useRef(0);
    const cameraFrame = useRef(0);
    const hover = useRef<Hit>(null);
    const dragging = useRef(false);
    /** The listener moved the camera since the web last changed: don't reframe it. */
    const userMoved = useRef(false);
    const pendingFit = useRef(false);
    const reducedMotion = useRef(false);
    const props = useRef({
      centerId,
      selectedId,
      selectedEdge,
      hintId,
      describeNode,
      describeEdge,
      onSelectNode,
      onSelectEdge,
      onOpenNode,
    });
    props.current = {
      centerId,
      selectedId,
      selectedEdge,
      hintId,
      describeNode,
      describeEdge,
      onSelectNode,
      onSelectEdge,
      onOpenNode,
    };

    const draw = useCallback(() => {
      frame.current = 0;
      const canvas = canvasRef.current;
      const context = canvas?.getContext('2d');
      const color = colorOf.current;
      if (!canvas || !context || !color) return;
      // While the layout is still moving the canvas draws at 1x: moving frames
      // are seen only briefly, and pixel count dominates their cost. Settled
      // frames are drawn sharp, at up to 2x.
      const settling = (simRef.current?.alpha() ?? 0) > SETTLED_ALPHA;
      const ratio = settling
        ? 1
        : Math.min(window.devicePixelRatio || 1, MAX_PIXEL_RATIO);
      const {width, height} = canvas.getBoundingClientRect();
      if (
        canvas.width !== Math.round(width * ratio) ||
        canvas.height !== Math.round(height * ratio)
      ) {
        canvas.width = Math.round(width * ratio);
        canvas.height = Math.round(height * ratio);
      }
      const {k, x, y} = transform.current;
      const now = performance.now();
      const {centerId: center, selectedId: selected} = props.current;
      const hovered = hover.current;
      const hoveredId = hovered?.kind === 'node' ? hovered.node.id : null;
      const hoveredEdge =
        hovered?.kind === 'edge' ? hovered.link.data.key : null;
      // What the eye should follow: the pointer first, then the selection.
      const focusId = hoveredId ?? props.current.hintId ?? selected;
      const focusEdge = hoveredEdge ?? props.current.selectedEdge;
      const lit = new Set<string>();
      if (focusId) {
        lit.add(focusId);
        neighbors.current.get(focusId)?.forEach(id => lit.add(id));
      }
      const focusLink = focusEdge
        ? simLinks.current.find(l => l.data.key === focusEdge)
        : undefined;
      if (focusLink) {
        lit.add((focusLink.source as SimNode).id);
        lit.add((focusLink.target as SimNode).id);
      }
      const focused = lit.size > 0;

      context.setTransform(ratio, 0, 0, ratio, 0, 0);
      context.clearRect(0, 0, width, height);
      context.translate(width / 2 + x, height / 2 + y);
      context.scale(k, k);
      const zoomScale = Math.sqrt(k);

      // Lines that look the same are stroked as one path: one raster pass per
      // style instead of one per line (dashed strokes are the costly part).
      const groups = new Map<
        string,
        {
          path: Path2D;
          alpha: number;
          color: string;
          width: number;
          dash: readonly number[];
        }
      >();
      for (const link of simLinks.current) {
        const a = link.source as SimNode;
        const b = link.target as SimNode;
        const category = dominantCategory(link.data.kinds);
        const encoding = CATEGORY_ENCODING[category];
        const isFocus =
          link.data.key === focusEdge ||
          (focusId !== null && (a.id === focusId || b.id === focusId));
        const alpha = !focused ? 0.6 : isFocus ? 1 : 0.1;
        const width = Math.round(lineWidth(link.data) * 2) / 2;
        const key = `${category}|${alpha}|${width}`;
        let group = groups.get(key);
        if (!group) {
          group = {
            path: new Path2D(),
            alpha,
            color: encoding.color,
            width,
            dash: encoding.dash,
          };
          groups.set(key, group);
        }
        group.path.moveTo(a.x ?? 0, a.y ?? 0);
        group.path.lineTo(b.x ?? 0, b.y ?? 0);
      }
      context.lineCap = 'round';
      for (const group of groups.values()) {
        context.globalAlpha = group.alpha;
        context.strokeStyle = color(group.color);
        context.lineWidth = group.width / zoomScale;
        context.setLineDash(group.dash.map(d => d / zoomScale));
        context.stroke(group.path);
      }
      context.setLineDash([]);
      // The connection in focus gets a light underlay so it reads over the rest.
      if (focusLink) {
        const a = focusLink.source as SimNode;
        const b = focusLink.target as SimNode;
        const encoding =
          CATEGORY_ENCODING[dominantCategory(focusLink.data.kinds)];
        context.globalAlpha = 0.9;
        context.beginPath();
        context.moveTo(a.x ?? 0, a.y ?? 0);
        context.lineTo(b.x ?? 0, b.y ?? 0);
        context.strokeStyle = color('--md-on-surface');
        context.lineWidth = (lineWidth(focusLink.data) + 4) / zoomScale;
        context.stroke();
        context.globalAlpha = 1;
        context.strokeStyle = color(encoding.color);
        context.lineWidth = lineWidth(focusLink.data) / zoomScale;
        context.setLineDash(encoding.dash.map(d => d / zoomScale));
        context.stroke();
        context.setLineDash([]);
      }

      // Artists.
      context.textAlign = 'center';
      context.textBaseline = 'middle';
      let fading = false;
      for (const node of simNodes.current.values()) {
        const nx = node.x ?? 0;
        const ny = node.y ?? 0;
        const age = (now - node.born) / FADE_MS;
        if (age < 1) fading = true;
        const dim = focused && !lit.has(node.id);
        const alpha = Math.min(1, Math.max(0, age)) * (dim ? 0.22 : 1);
        context.globalAlpha = alpha;
        context.drawImage(
          spriteFor(node.hue),
          nx - node.r,
          ny - node.r,
          node.r * 2,
          node.r * 2,
        );
        if (node.r * k >= 9) {
          context.fillStyle = '#fff';
          context.font = `700 ${node.r * 0.95}px Roboto Variable, Roboto, system-ui, sans-serif`;
          context.fillText(node.initial, nx, ny + node.r * 0.04);
        }
        const isCenter = node.id === center;
        const isSelected = node.id === selected;
        const isHovered = node.id === hoveredId;
        if (isCenter || isSelected || isHovered || node.data.expanded) {
          context.beginPath();
          context.arc(nx, ny, node.r + 3 / zoomScale, 0, 2 * Math.PI);
          context.lineWidth =
            (isCenter || isSelected ? 2.5 : isHovered ? 2 : 1) / zoomScale;
          context.strokeStyle = isSelected
            ? color('--md-on-surface')
            : isCenter
              ? color('--brand')
              : isHovered
                ? color('--md-on-surface')
                : color('--md-outline');
          context.stroke();
        }
      }
      context.globalAlpha = 1;

      // Names, in screen space at a constant size. Most important first; a name
      // that would overlap one already placed is left out until there's room.
      context.setTransform(ratio, 0, 0, ratio, 0, 0);
      context.textBaseline = 'top';
      const halo = color('--md-surface');
      const ink = color('--md-on-surface');
      const quiet = color('--md-on-surface-variant');
      const candidates: {node: SimNode; rank: number}[] = [];
      for (const node of simNodes.current.values()) {
        if (focused && !lit.has(node.id)) continue;
        const rank =
          node.id === center
            ? 0
            : node.id === selected || node.id === hoveredId
              ? 1
              : node.data.expanded
                ? 2
                : focused
                  ? 3
                  : k >= 0.75
                    ? 4
                    : -1;
        if (rank >= 0) candidates.push({node, rank});
      }
      candidates.sort(
        (p, q) => p.rank - q.rank || q.node.weight - p.node.weight,
      );
      const placed: [number, number, number, number][] = [];
      let drawn = 0;
      for (const {node, rank} of candidates) {
        if (drawn >= MAX_LABELS) break;
        const strong = rank <= 1;
        const size = node.id === center ? LABEL_FONT + 2 : LABEL_FONT;
        const sx = width / 2 + x + (node.x ?? 0) * k;
        const sy = height / 2 + y + (node.y ?? 0) * k + node.r * k + 6;
        if (sx < -80 || sx > width + 80 || sy < -20 || sy > height + 20)
          continue;
        const w = node.labelWidth * (size / LABEL_FONT) + 8;
        const box: [number, number, number, number] = [
          sx - w / 2,
          sy - 2,
          sx + w / 2,
          sy + size + 4,
        ];
        const collides = placed.some(
          p => box[0] < p[2] && box[2] > p[0] && box[1] < p[3] && box[3] > p[1],
        );
        if (collides && !strong) continue;
        placed.push(box);
        drawn++;
        context.font = `${strong || rank === 2 ? 700 : 500} ${size}px Roboto Variable, Roboto, system-ui, sans-serif`;
        context.lineJoin = 'round';
        context.lineWidth = 4;
        context.strokeStyle = halo;
        context.strokeText(node.data.name, sx, sy);
        context.fillStyle = rank <= 2 ? ink : quiet;
        context.fillText(node.data.name, sx, sy);
      }

      // Keep animating while artists are still fading in.
      if (fading && !frame.current) frame.current = requestAnimationFrame(draw);
    }, []);

    const scheduleDraw = useCallback(() => {
      if (!frame.current) frame.current = requestAnimationFrame(draw);
    }, [draw]);

    /** Moves the camera, smoothly unless the listener prefers reduced motion. */
    const moveCamera = useCallback((target: ZoomTransform) => {
      const canvas = canvasRef.current;
      const behavior = zoomRef.current;
      if (!canvas || !behavior) return;
      cancelAnimationFrame(cameraFrame.current);
      const selection = select(canvas);
      if (reducedMotion.current) {
        selection.call(behavior.transform, target);
        return;
      }
      const from = transform.current;
      const started = performance.now();
      const step = (now: number) => {
        const t = Math.min(1, (now - started) / CAMERA_MS);
        const eased = 1 - Math.pow(1 - t, 3);
        selection.call(
          behavior.transform,
          zoomIdentity
            .translate(
              from.x + (target.x - from.x) * eased,
              from.y + (target.y - from.y) * eased,
            )
            .scale(from.k + (target.k - from.k) * eased),
        );
        if (t < 1) cameraFrame.current = requestAnimationFrame(step);
      };
      cameraFrame.current = requestAnimationFrame(step);
    }, []);

    const fit = useCallback(() => {
      const canvas = canvasRef.current;
      const list = [...simNodes.current.values()];
      if (!canvas || list.length === 0) return;
      const {width, height} = canvas.getBoundingClientRect();
      if (width === 0 || height === 0) return;
      let minX = Infinity;
      let maxX = -Infinity;
      let minY = Infinity;
      let maxY = -Infinity;
      for (const node of list) {
        minX = Math.min(minX, (node.x ?? 0) - node.r);
        maxX = Math.max(maxX, (node.x ?? 0) + node.r);
        minY = Math.min(minY, (node.y ?? 0) - node.r);
        maxY = Math.max(maxY, (node.y ?? 0) + node.r + 18);
      }
      // On small canvases the overlays take less room; scale the padding down.
      const shrink = Math.min(1, height / 520, width / 520);
      const top = PADDING.top * shrink;
      const bottom = PADDING.bottom * shrink;
      const left = PADDING.left * shrink;
      const right = PADDING.right * shrink;
      const spanX = Math.max(1, maxX - minX);
      const spanY = Math.max(1, maxY - minY);
      const k = Math.max(
        0.25,
        Math.min(
          1.5,
          (width - left - right) / spanX,
          (height - top - bottom) / spanY,
        ),
      );
      const cx = (minX + maxX) / 2;
      const cy = (minY + maxY) / 2;
      moveCamera(
        zoomIdentity
          .translate((left - right) / 2 - cx * k, (top - bottom) / 2 - cy * k)
          .scale(k),
      );
    }, [moveCamera]);

    /** What is under a point given in canvas (CSS pixel) coordinates. */
    const hitTest = useCallback((px: number, py: number): Hit => {
      const canvas = canvasRef.current;
      if (!canvas) return null;
      const {width, height} = canvas.getBoundingClientRect();
      const {k, x, y} = transform.current;
      const wx = (px - width / 2 - x) / k;
      const wy = (py - height / 2 - y) / k;
      let best: SimNode | null = null;
      let bestDistance = Infinity;
      for (const node of simNodes.current.values()) {
        const d = Math.hypot((node.x ?? 0) - wx, (node.y ?? 0) - wy) - node.r;
        if (d < bestDistance) {
          best = node;
          bestDistance = d;
        }
      }
      if (best && bestDistance < 6 / k) return {kind: 'node', node: best};
      let nearest: SimLink | null = null;
      let nearestDistance = 7 / k;
      for (const link of simLinks.current) {
        const a = link.source as SimNode;
        const b = link.target as SimNode;
        const d = distanceToSegment(
          wx,
          wy,
          a.x ?? 0,
          a.y ?? 0,
          b.x ?? 0,
          b.y ?? 0,
        );
        if (d < nearestDistance) {
          nearest = link;
          nearestDistance = d;
        }
      }
      return nearest ? {kind: 'edge', link: nearest} : null;
    }, []);

    const showTip = useCallback((hit: Hit, px: number, py: number) => {
      const tip = tipRef.current;
      const canvas = canvasRef.current;
      if (!tip || !canvas) return;
      if (!hit || dragging.current) {
        tip.hidden = true;
        return;
      }
      tip.textContent =
        hit.kind === 'node'
          ? props.current.describeNode(hit.node.data)
          : props.current.describeEdge(
              hit.link.data,
              (hit.link.source as SimNode).data,
              (hit.link.target as SimNode).data,
            );
      tip.hidden = false;
      const {width, height} = canvas.getBoundingClientRect();
      const tipWidth = tip.offsetWidth;
      const tipHeight = tip.offsetHeight;
      const left = Math.max(8, Math.min(width - tipWidth - 8, px + 14));
      const top =
        py + 18 + tipHeight > height - 8 ? py - tipHeight - 12 : py + 18;
      tip.style.transform = `translate(${Math.round(left)}px, ${Math.round(top)}px)`;
    }, []);

    // One-time setup: simulation, zoom, drag, theme tracking, resize.
    useEffect(() => {
      const canvas = canvasRef.current!;
      const colors = colorResolver(canvas.parentElement ?? document.body);
      colorOf.current = colors;
      const motion = window.matchMedia('(prefers-reduced-motion: reduce)');
      reducedMotion.current = motion.matches;

      const frameIfReady = () => {
        if (!pendingFit.current) return;
        pendingFit.current = false;
        fit();
      };
      const simulation = forceSimulation<SimNode, SimLink>()
        .force(
          'charge',
          forceManyBody<SimNode>().strength(-260).distanceMax(560),
        )
        .force(
          'collide',
          forceCollide<SimNode>(node => node.r + 14),
        )
        .force('x', forceX<SimNode>(0).strength(0.035))
        .force('y', forceY<SimNode>(0).strength(0.035))
        .on('tick', () => {
          if (simulation.alpha() < FRAME_ALPHA) frameIfReady();
          scheduleDraw();
        })
        .on('end', () => {
          // The first framing is taken while the layout is still easing out;
          // correct it once everything has stopped, if the view is still ours.
          if (pendingFit.current || !userMoved.current) {
            pendingFit.current = false;
            fit();
          }
          scheduleDraw();
        });
      if (motion.matches) simulation.alphaDecay(0.2);
      simRef.current = simulation;

      const zoomBehavior = zoom<HTMLCanvasElement, unknown>()
        .scaleExtent([0.2, 4])
        .on('zoom', event => {
          transform.current = event.transform as ZoomTransform;
          if (event.sourceEvent) {
            userMoved.current = true;
            pendingFit.current = false;
            cancelAnimationFrame(cameraFrame.current);
            if (tipRef.current) tipRef.current.hidden = true;
          }
          scheduleDraw();
        });
      zoomRef.current = zoomBehavior;

      const toWorld = (event: {sourceEvent: Event}): [number, number] => {
        const [px, py] = pointer(event.sourceEvent, canvas);
        const {width, height} = canvas.getBoundingClientRect();
        const {k, x, y} = transform.current;
        return [(px - width / 2 - x) / k, (py - height / 2 - y) / k];
      };
      const dragBehavior = drag<HTMLCanvasElement, unknown>()
        .subject(event => {
          const [px, py] = pointer(event.sourceEvent, canvas);
          const hit = hitTest(px, py);
          return hit?.kind === 'node' ? hit.node : undefined;
        })
        .on('start', event => {
          const node = event.subject as SimNode;
          node.fx = node.x;
          node.fy = node.y;
        })
        .on('drag', event => {
          const node = event.subject as SimNode;
          if (!dragging.current) {
            dragging.current = true;
            simulation.alphaTarget(0.2).restart();
            canvas.style.cursor = 'grabbing';
            if (tipRef.current) tipRef.current.hidden = true;
          }
          const [wx, wy] = toWorld(event);
          node.fx = wx;
          node.fy = wy;
        })
        .on('end', event => {
          const node = event.subject as SimNode;
          node.fx = null;
          node.fy = null;
          if (dragging.current) {
            dragging.current = false;
            // Moving an artist is the listener arranging the web: keep their view.
            userMoved.current = true;
            simulation.alphaTarget(0);
            canvas.style.cursor = 'grab';
          }
        });
      // Drag before zoom: a press on an artist moves it, anywhere else pans.
      select(canvas)
        .call(dragBehavior)
        .call(zoomBehavior)
        .on('dblclick.zoom', null);

      const refreshColors = () => {
        colors.reset();
        scheduleDraw();
      };
      const themeObserver = new MutationObserver(refreshColors);
      themeObserver.observe(document.documentElement, {
        attributes: true,
        attributeFilter: ['data-theme'],
      });
      const media = window.matchMedia('(prefers-color-scheme: dark)');
      media.addEventListener('change', refreshColors);
      const resize = new ResizeObserver(scheduleDraw);
      resize.observe(canvas);
      // The label font may arrive after the first frame; redraw when it does.
      void document.fonts?.ready.then(() => {
        for (const node of simNodes.current.values()) node.labelWidth = 0;
        measureLabels(canvas, simNodes.current.values());
        scheduleDraw();
      });

      return () => {
        simulation.stop();
        select(canvas).on('.zoom', null).on('.drag', null);
        themeObserver.disconnect();
        media.removeEventListener('change', refreshColors);
        resize.disconnect();
        colors.dispose();
        cancelAnimationFrame(frame.current);
        cancelAnimationFrame(cameraFrame.current);
        // Clear the handle: a stale one would make scheduleDraw think a frame is
        // still queued, and the web would never draw again (seen under
        // StrictMode, which runs this cleanup once right after mounting).
        frame.current = 0;
      };
    }, [fit, hitTest, scheduleDraw]);

    // Data changes: keep positions of known nodes, seed new ones near their neighbor.
    useEffect(() => {
      const simulation = simRef.current;
      const canvas = canvasRef.current;
      if (!simulation || !canvas) return;
      const previous = simNodes.current;
      const next = new Map<string, SimNode>();
      const adjacency = new Map<string, Set<string>>();
      const weights = new Map<string, number>();
      for (const edge of edges) {
        for (const [from, to] of [
          [edge.a, edge.b],
          [edge.b, edge.a],
        ] as const) {
          let set = adjacency.get(from);
          if (!set) adjacency.set(from, (set = new Set()));
          set.add(to);
          weights.set(from, Math.max(weights.get(from) ?? 0, edge.strength));
        }
      }
      const now = performance.now();
      const isFirst = previous.size === 0;
      let added = 0;
      for (const node of nodes) {
        const weight = weights.get(node.id) ?? 0;
        const r = radiusOf(node, weight, node.id === centerId);
        const existing = previous.get(node.id);
        if (existing) {
          existing.data = node;
          existing.r = r;
          existing.weight = weight;
          next.set(node.id, existing);
          continue;
        }
        // A new artist starts beside the one that brought it in, on a ring, so
        // the web opens outward instead of exploding from one point.
        let anchor: SimNode | undefined;
        for (const other of adjacency.get(node.id) ?? []) {
          anchor = previous.get(other);
          if (anchor) break;
        }
        const angle = added++ * 2.399963; // the golden angle spreads them evenly
        const distance = anchor ? 30 + anchor.r : node.id === centerId ? 0 : 90;
        next.set(node.id, {
          id: node.id,
          data: node,
          r,
          hue: hueOf(node.name),
          initial: initialOf(node.name),
          born: isFirst ? now - FADE_MS : now,
          labelWidth: 0,
          weight,
          x: (anchor?.x ?? 0) + Math.cos(angle) * distance,
          y: (anchor?.y ?? 0) + Math.sin(angle) * distance,
        });
      }
      measureLabels(canvas, next.values());
      simNodes.current = next;
      neighbors.current = adjacency;
      simLinks.current = edges
        .filter(e => next.has(e.a) && next.has(e.b))
        .map(e => ({source: next.get(e.a)!, target: next.get(e.b)!, data: e}));
      if (hover.current) {
        hover.current = null;
        if (tipRef.current) tipRef.current.hidden = true;
      }
      simulation.nodes([...next.values()]);
      simulation.force(
        'link',
        forceLink<SimNode, SimLink>(simLinks.current)
          .id(n => n.id)
          .distance(l => 84 + 56 / (1 + l.data.strength))
          .strength(l => 0.25 + Math.min(0.5, l.data.strength / 20)),
      );
      // Frame the new web once it settles, unless the listener has taken over
      // the camera (then their view stays put).
      if (isFirst) userMoved.current = false;
      pendingFit.current = isFirst || !userMoved.current;
      simulation.alpha(isFirst ? 0.9 : 0.5).restart();
    }, [nodes, edges, centerId]);

    useEffect(scheduleDraw, [
      selectedId,
      selectedEdge,
      hintId,
      centerId,
      scheduleDraw,
    ]);

    useImperativeHandle(
      ref,
      () => ({
        fit() {
          userMoved.current = false;
          fit();
        },
        zoomBy(factor: number) {
          const current = transform.current;
          const k = Math.max(0.2, Math.min(4, current.k * factor));
          const scale = k / current.k;
          moveCamera(
            zoomIdentity
              .translate(current.x * scale, current.y * scale)
              .scale(k),
          );
          userMoved.current = true;
        },
        focus(id: string) {
          const node = simNodes.current.get(id);
          if (!node) return;
          const k = Math.max(transform.current.k, 0.9);
          moveCamera(
            zoomIdentity
              .translate(-(node.x ?? 0) * k, -(node.y ?? 0) * k)
              .scale(k),
          );
          userMoved.current = true;
        },
      }),
      [fit, moveCamera],
    );

    function localPoint(event: {clientX: number; clientY: number}) {
      const rect = canvasRef.current!.getBoundingClientRect();
      return [event.clientX - rect.left, event.clientY - rect.top] as const;
    }

    return (
      <div className="web__canvas">
        <canvas
          ref={canvasRef}
          role="img"
          aria-label={label}
          data-node-count={nodes.length}
          onPointerMove={event => {
            if (event.pointerType === 'touch' || dragging.current) return;
            const [px, py] = localPoint(event);
            const hit = hitTest(px, py);
            const previous = hover.current;
            const same =
              hit?.kind === previous?.kind &&
              (hit?.kind === 'node'
                ? hit.node === (previous as typeof hit).node
                : hit?.kind === 'edge'
                  ? hit.link === (previous as typeof hit).link
                  : true);
            hover.current = hit;
            canvasRef.current!.style.cursor = hit ? 'pointer' : 'grab';
            showTip(hit, px, py);
            if (!same) scheduleDraw();
          }}
          onPointerLeave={() => {
            if (!hover.current) return;
            hover.current = null;
            if (tipRef.current) tipRef.current.hidden = true;
            scheduleDraw();
          }}
          onClick={event => {
            const hit = hitTest(...localPoint(event));
            if (hit?.kind === 'node') props.current.onSelectNode(hit.node.id);
            else if (hit?.kind === 'edge')
              props.current.onSelectEdge(
                (hit.link.source as SimNode).id,
                (hit.link.target as SimNode).id,
              );
            else props.current.onSelectNode(null);
          }}
          onDoubleClick={event => {
            const hit = hitTest(...localPoint(event));
            if (hit?.kind === 'node') props.current.onOpenNode(hit.node.id);
          }}
        />
        <div ref={tipRef} className="web__tip" role="presentation" hidden />
      </div>
    );
  },
);

/** Measures names not measured yet, at the label font. */
function measureLabels(
  canvas: HTMLCanvasElement,
  nodes: Iterable<SimNode>,
): void {
  const context = canvas.getContext('2d');
  if (!context) return;
  context.save();
  context.setTransform(1, 0, 0, 1, 0, 0);
  context.font = `700 ${LABEL_FONT}px Roboto Variable, Roboto, system-ui, sans-serif`;
  for (const node of nodes) {
    if (!node.labelWidth)
      node.labelWidth = context.measureText(node.data.name).width;
  }
  context.restore();
}
