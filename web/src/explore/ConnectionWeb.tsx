/**
 * The connection web, drawn on a canvas (SVG doesn't hold up past ~300 nodes).
 *
 * Layout (docs/design/connection-web-v5.md): the starting artist is pinned in
 * the middle and their direct connections sit on orbits by role (performed
 * together, made the music, other credits), so the web has a shape a listener
 * can read at a glance. Artists opened later bloom around themselves with the
 * usual force layout, outside the orbits. Faces are sized by how widely known
 * the artist is (public listener counts); lines by how much they made together.
 *
 * d3-force lays it out, d3-zoom pans and zooms, d3-drag moves an artist.
 * Artists are drawn as their photo when we have one, over their generated
 * cover (the same art as everywhere else in the app), so a slow or missing
 * photo never leaves a hole. Lines carry the kind of connection (color and
 * dash) and its strength (width). Pointing at something lights up its
 * neighborhood with a soft glow and names it; clicking or tapping selects it;
 * double-clicking or double-tapping an artist opens their connections.
 *
 * The canvas is focusable: arrow keys move between artists, Enter opens one,
 * Escape clears, + and - zoom, 0 fits. The list view next to it carries the
 * same content for screen-reader users (AC-2.3).
 *
 * Frames are cheap on purpose: covers, photos and glows are pre-rendered
 * sprites, lines of one style are stroked as one path, and the per-frame
 * collections are reused rather than reallocated.
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
import {select} from 'd3-selection';
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
  useId,
  useImperativeHandle,
  useRef,
  type KeyboardEvent,
} from 'react';

import {initialOf} from '../components/ArtistRow';
import {CATEGORY_ENCODING, dominantCategory} from '../components/encoding';
import {hueOf} from '../components/Shelf';

import {
  orbitOf,
  ORBITS,
  type Orbit,
  type WebEdge,
  type WebNode,
} from './graphState';
import {onPhotoReady, photoFor} from './photos';
import {
  ARROWS,
  easeInOut,
  interpolateView,
  nearestInDirection,
} from './spatial';

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
  /** How much to show this artist: reach and strength together (label priority). */
  weight: number;
  /** The orbit, for direct connections of the starting artist. */
  orbit: Orbit | null;
}

interface Ring {
  orbit: Orbit;
  radius: number;
  count: number;
}

export interface StoryCard {
  title: string;
  subtitle: string;
  brand: string;
}

interface SimLink extends SimulationLinkDatum<SimNode> {
  data: WebEdge;
}

export interface ConnectionWebHandle {
  fit: () => void;
  zoomBy: (factor: number) => void;
  focus: (id: string) => void;
  /**
   * The web as a 1080x1920 story image (PNG), or null if the browser can't
   * make one. Drawn on the device; nothing is uploaded.
   */
  snapshot: (card: StoryCard) => Promise<Blob | null>;
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
  /** How to use the web from the keyboard (read after the label). */
  keyHelp: string;
  /** Text for the pointer tooltip and the keyboard announcement. */
  describeNode: (node: WebNode) => string;
  describeEdge: (edge: WebEdge, a: WebNode, b: WebNode) => string;
  /** The label drawn on an orbit ("Features · 9"). */
  describeOrbit: (orbit: Orbit, count: number) => string;
  onSelectNode: (id: string | null) => void;
  onSelectEdge: (a: string, b: string) => void;
  /** Double-click, double-tap or Enter: open this artist's connections. */
  onOpenNode: (id: string) => void;
}

const CENTER_RADIUS = 30;
/** The closest the camera frames a web: small webs stay life-size instead of ballooning. */
const MAX_FIT_ZOOM = 1.1;
const MAX_PIXEL_RATIO = 2;
/** Below this simulation alpha the layout reads as still; full-quality frames return. */
const SETTLED_ALPHA = 0.05;
/** Below this alpha the layout is close enough to frame the camera on it. */
const FRAME_ALPHA = 0.14;
const FADE_MS = 380;
const PHOTO_FADE_MS = 260;
const CAMERA_MS = 620;
const DOUBLE_TAP_MS = 350;
const LABEL_FONT = 12;
const MAX_LABELS = 70;
/** Below this zoom names give way to faces (collisions already thin them out). */
const LABEL_MIN_ZOOM = 0.38;
const FONT_STACK =
  "'Google Sans Flex Variable', 'Roboto Variable', Roboto, system-ui, sans-serif";
const LABEL_FONTS = {
  strong: `700 ${LABEL_FONT}px ${FONT_STACK}`,
  center: `750 ${LABEL_FONT + 2}px ${FONT_STACK}`,
  quiet: `500 ${LABEL_FONT}px ${FONT_STACK}`,
};
/** Room kept clear of the overlays (title and tools above, legend below). */
const PADDING = {top: 150, right: 40, bottom: 150, left: 40};
/** The innermost orbit's smallest radius, and the gap to each next one out. */
const FIRST_ORBIT = 140;
const ORBIT_GAP = 78;
/** Room around each artist on an orbit (beyond its diameter), in world units. */
const ORBIT_SPACING = 30;
/** Artists opened later bloom beyond the outer orbit, by this much. */
const BLOOM_OFFSET = 130;
/** How strongly artists are held on their orbit (and the bloom, beyond it). */
const ORBIT_STRENGTH = 0.9;
const BLOOM_STRENGTH = 0.03;
/** Half the width kept clear at the top of each orbit for its name, in world units. */
const ORBIT_LABEL_HALF = 46;
/** How far lines bow, as a share of their length (a gentle, consistent swirl). */
const BEND = 0.12;
/** The pulse that runs along lines in focus: dash, gap (px) and speed (px/s). */
const PULSE = {dash: 3, gap: 15, speed: 34};
const SPRITE_SIZE = 96;
const GLOW_SIZE = 128;
const HUE_STEP = 12;

const lineWidth = (edge: WebEdge) =>
  Math.min(5.5, 0.9 + 1.05 * Math.log2(1 + edge.strength));

/** Orders of magnitude of listeners (0 when unknown). */
const reachOf = (node: WebNode) =>
  node.listeners ? Math.log10(1 + node.listeners) : 0;

/**
 * Radius in world units: reach sets the size (about 9 at a thousand
 * listeners, 13 at ten thousand, 16 past a hundred thousand), strength adds a
 * little, artists without a photo or listener data stay small and quiet.
 */
export function radiusOf(
  node: WebNode,
  strength: number,
  isCenter: boolean,
): number {
  if (isCenter) return CENTER_RADIUS;
  const reach = reachOf(node);
  const fromReach = Math.max(0, Math.min(9, (reach - 2.6) * 3.4));
  const fromStrength = Math.min(2, 0.4 * Math.log2(1 + strength));
  const quiet = !node.image && !node.listeners ? -1.5 : 0;
  const base = 8 + fromReach + fromStrength + quiet;
  return node.expanded ? base + 2 : base;
}

/** Label priority: reach first (who people know), then how much they made together. */
const weightOf = (node: WebNode, strength: number) =>
  1.6 * reachOf(node) + Math.log2(1 + strength);

/**
 * The control point that bows a line from (ax, ay) to (bx, by). Always to the
 * same side of the direction of travel, so spokes from the middle swirl gently
 * the same way, like an orbit, instead of crossing at random.
 */
function bow(ax: number, ay: number, bx: number, by: number): [number, number] {
  const mx = (ax + bx) / 2;
  const my = (ay + by) / 2;
  return [mx - (by - ay) * BEND, my + (bx - ax) * BEND];
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

const bucketOf = (hue: number) => Math.round(hue / HUE_STEP) * HUE_STEP;

/** The generated cover for a hue, drawn once and reused for every node with it. */
const sprites = new Map<number, HTMLCanvasElement>();
function spriteFor(hue: number): HTMLCanvasElement {
  const bucket = bucketOf(hue);
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
      // Faint record grooves, as on the generated covers elsewhere.
      context.strokeStyle = 'rgb(255 255 255 / 6%)';
      context.lineWidth = 1;
      for (let r = 10; r < half; r += 7) {
        context.beginPath();
        context.arc(half, half, r, 0, 2 * Math.PI);
        context.stroke();
      }
    }
    sprites.set(bucket, sprite);
  }
  return sprite;
}

/** A soft halo in an artist's own color, for the lit neighborhood. */
const glows = new Map<number, HTMLCanvasElement>();
function glowFor(hue: number): HTMLCanvasElement {
  const bucket = bucketOf(hue);
  let glow = glows.get(bucket);
  if (!glow) {
    glow = document.createElement('canvas');
    glow.width = glow.height = GLOW_SIZE;
    const context = glow.getContext('2d');
    if (context) {
      const half = GLOW_SIZE / 2;
      const gradient = context.createRadialGradient(
        half,
        half,
        half * 0.3,
        half,
        half,
        half,
      );
      gradient.addColorStop(0, `hsl(${bucket} 90% 62% / 70%)`);
      gradient.addColorStop(0.45, `hsl(${bucket} 90% 58% / 22%)`);
      gradient.addColorStop(1, `hsl(${bucket} 90% 55% / 0%)`);
      context.fillStyle = gradient;
      context.fillRect(0, 0, GLOW_SIZE, GLOW_SIZE);
    }
    glows.set(bucket, glow);
  }
  return glow;
}

/** A soft shadow under each artist, so overlapping covers separate. */
let shadowSprite: HTMLCanvasElement | null = null;
function shadow(): HTMLCanvasElement {
  if (!shadowSprite) {
    shadowSprite = document.createElement('canvas');
    shadowSprite.width = shadowSprite.height = 64;
    const context = shadowSprite.getContext('2d');
    if (context) {
      const gradient = context.createRadialGradient(32, 32, 16, 32, 32, 32);
      gradient.addColorStop(0, 'rgb(0 0 0 / 55%)');
      gradient.addColorStop(1, 'rgb(0 0 0 / 0%)');
      context.fillStyle = gradient;
      context.fillRect(0, 0, 64, 64);
    }
  }
  return shadowSprite;
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

/** Distance from a point to a bowed line, approximated by two segments through its middle. */
function distanceToBow(
  px: number,
  py: number,
  ax: number,
  ay: number,
  bx: number,
  by: number,
): number {
  const [cx, cy] = bow(ax, ay, bx, by);
  // The curve's midpoint (t = 0.5) of the quadratic through the control point.
  const mx = 0.25 * ax + 0.5 * cx + 0.25 * bx;
  const my = 0.25 * ay + 0.5 * cy + 0.25 * by;
  return Math.min(
    distanceToSegment(px, py, ax, ay, mx, my),
    distanceToSegment(px, py, mx, my, bx, by),
  );
}

/** A link's ends, the one nearer the middle first, so every spoke bows the same way. */
function inward(a: SimNode, b: SimNode): [SimNode, SimNode] {
  const da = (a.x ?? 0) ** 2 + (a.y ?? 0) ** 2;
  const db = (b.x ?? 0) ** 2 + (b.y ?? 0) ** 2;
  return da <= db ? [a, b] : [b, a];
}

type Hit = {kind: 'node'; node: SimNode} | {kind: 'edge'; link: SimLink} | null;

interface StrokeGroup {
  path: Path2D;
  alpha: number;
  color: string;
  width: number;
  dash: readonly number[];
  lit: boolean;
}

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
      keyHelp,
      describeNode,
      describeEdge,
      describeOrbit,
      onSelectNode,
      onSelectEdge,
      onOpenNode,
    },
    ref,
  ) => {
    const helpId = useId();
    const canvasRef = useRef<HTMLCanvasElement>(null);
    const tipRef = useRef<HTMLDivElement>(null);
    const liveRef = useRef<HTMLParagraphElement>(null);
    const simRef = useRef<Simulation<SimNode, SimLink> | null>(null);
    const simNodes = useRef(new Map<string, SimNode>());
    const simLinks = useRef<SimLink[]>([]);
    const neighbors = useRef(new Map<string, Set<string>>());
    const rings = useRef<Ring[]>([]);
    const transform = useRef<ZoomTransform>(zoomIdentity);
    const zoomRef = useRef<ZoomBehavior<HTMLCanvasElement, unknown> | null>(
      null,
    );
    const colorOf = useRef<ReturnType<typeof colorResolver> | null>(null);
    const frame = useRef(0);
    const cameraFrame = useRef(0);
    const hover = useRef<Hit>(null);
    const dragging = useRef(false);
    const lastTap = useRef<{id: string; at: number} | null>(null);
    const lastOpen = useRef(0);
    /** The listener moved the camera since the web last changed: don't reframe it. */
    const userMoved = useRef(false);
    const pendingFit = useRef(false);
    const reducedMotion = useRef(false);
    /** While drawing the share image: everything lit, nothing hovered or selected. */
    const exporting = useRef(false);
    // Reused every frame instead of reallocated.
    const scratch = useRef({
      lit: new Set<string>(),
      groups: new Map<string, StrokeGroup>(),
      candidates: [] as {node: SimNode; rank: number}[],
      placed: [] as number[],
    });
    const props = useRef({
      centerId,
      selectedId,
      selectedEdge,
      hintId,
      describeNode,
      describeEdge,
      describeOrbit,
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
      describeOrbit,
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
      const width = canvas.clientWidth;
      const height = canvas.clientHeight;
      if (
        canvas.width !== Math.round(width * ratio) ||
        canvas.height !== Math.round(height * ratio)
      ) {
        canvas.width = Math.round(width * ratio);
        canvas.height = Math.round(height * ratio);
      }
      const {k, x, y} = transform.current;
      const now = performance.now();
      const center = props.current.centerId;
      // The share image shows no selection or pointer.
      const selected = exporting.current ? null : props.current.selectedId;
      const hovered = exporting.current ? null : hover.current;
      const hoveredId = hovered?.kind === 'node' ? hovered.node.id : null;
      const hoveredEdge =
        hovered?.kind === 'edge' ? hovered.link.data.key : null;
      // What the eye should follow: the pointer first, then the selection.
      const focusId = exporting.current
        ? null
        : (hoveredId ?? props.current.hintId ?? selected);
      const focusEdge = exporting.current
        ? null
        : (hoveredEdge ?? props.current.selectedEdge);
      const {lit, groups, candidates, placed} = scratch.current;
      lit.clear();
      if (focusId) {
        lit.add(focusId);
        neighbors.current.get(focusId)?.forEach(id => lit.add(id));
      }
      let focusLink: SimLink | undefined;
      if (focusEdge)
        for (const link of simLinks.current)
          if (link.data.key === focusEdge) {
            focusLink = link;
            break;
          }
      if (focusLink) {
        lit.add((focusLink.source as SimNode).id);
        lit.add((focusLink.target as SimNode).id);
      }
      const focused = lit.size > 0;
      let animating = false;

      context.setTransform(ratio, 0, 0, ratio, 0, 0);
      context.clearRect(0, 0, width, height);
      context.translate(width / 2 + x, height / 2 + y);
      context.scale(k, k);
      const zoomScale = Math.sqrt(k);

      // The orbits: faint guides around the start, each named on its top edge.
      const centerNode = center ? simNodes.current.get(center) : undefined;
      if (centerNode && rings.current.length) {
        const ox = centerNode.x ?? 0;
        const oy = centerNode.y ?? 0;
        context.lineWidth = 1 / zoomScale;
        context.setLineDash([2 / zoomScale, 6 / zoomScale]);
        context.strokeStyle = color('--md-on-surface');
        context.globalAlpha = focused ? 0.06 : 0.14;
        for (const ring of rings.current) {
          context.beginPath();
          context.arc(ox, oy, ring.radius, 0, 2 * Math.PI);
          context.stroke();
        }
        context.setLineDash([]);
        context.globalAlpha = 1;
      }

      // Lines that look the same are stroked as one path: one raster pass per
      // style instead of one per line (dashed strokes are the costly part).
      groups.clear();
      for (const link of simLinks.current) {
        const a = link.source as SimNode;
        const b = link.target as SimNode;
        const category = dominantCategory(link.data.kinds);
        const encoding = CATEGORY_ENCODING[category];
        const isFocus =
          link.data.key === focusEdge ||
          (focusId !== null && (a.id === focusId || b.id === focusId));
        // New lines fade in with the newer of their two artists (in steps, so
        // they still group into a few paths).
        const age = Math.min(now - a.born, now - b.born) / FADE_MS;
        const fade = age >= 1 ? 1 : Math.max(0.25, Math.ceil(age * 4) / 4);
        if (age < 1) animating = true;
        const alpha = (!focused ? 0.42 : isFocus ? 1 : 0.06) * fade;
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
            lit: focused && isFocus,
          };
          groups.set(key, group);
        }
        const [p, q] = inward(a, b);
        const [cx, cy] = bow(p.x ?? 0, p.y ?? 0, q.x ?? 0, q.y ?? 0);
        group.path.moveTo(p.x ?? 0, p.y ?? 0);
        group.path.quadraticCurveTo(cx, cy, q.x ?? 0, q.y ?? 0);
      }
      context.lineCap = 'round';
      // The lit neighborhood's lines get a soft wide underglow first.
      for (const group of groups.values()) {
        if (!group.lit) continue;
        context.globalAlpha = 0.18;
        context.strokeStyle = color(group.color);
        context.lineWidth = (group.width + 7) / zoomScale;
        context.setLineDash([]);
        context.stroke(group.path);
      }
      for (const group of groups.values()) {
        context.globalAlpha = group.alpha;
        context.strokeStyle = color(group.color);
        context.lineWidth = group.width / zoomScale;
        context.setLineDash(
          group.dash.length ? group.dash.map(d => d / zoomScale) : [],
        );
        context.stroke(group.path);
      }
      // Lines in focus carry a slow pulse outward, so the lit neighborhood
      // reads as alive. Still when the listener prefers reduced motion.
      if (focused) {
        context.globalAlpha = 0.7;
        context.strokeStyle = '#fff';
        context.setLineDash([PULSE.dash / zoomScale, PULSE.gap / zoomScale]);
        context.lineDashOffset = reducedMotion.current
          ? 0
          : (-(now / 1000) * PULSE.speed) / zoomScale;
        for (const group of groups.values()) {
          if (!group.lit) continue;
          context.lineWidth = Math.max(1.2, group.width * 0.45) / zoomScale;
          context.stroke(group.path);
        }
        context.lineDashOffset = 0;
        if (!reducedMotion.current) animating = true;
      }
      context.setLineDash([]);
      // The connection in focus gets a light underlay so it reads over the rest.
      if (focusLink) {
        const [a, b] = inward(
          focusLink.source as SimNode,
          focusLink.target as SimNode,
        );
        const encoding =
          CATEGORY_ENCODING[dominantCategory(focusLink.data.kinds)];
        const [cx, cy] = bow(a.x ?? 0, a.y ?? 0, b.x ?? 0, b.y ?? 0);
        context.globalAlpha = 0.9;
        context.beginPath();
        context.moveTo(a.x ?? 0, a.y ?? 0);
        context.quadraticCurveTo(cx, cy, b.x ?? 0, b.y ?? 0);
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

      // Glows under the lit artists (and always a faint one under the start).
      for (const node of simNodes.current.values()) {
        const isCenter = node.id === center;
        const isFocus = node.id === focusId;
        if (!(focused && lit.has(node.id)) && !isCenter) continue;
        const size = node.r * (isFocus ? 4.2 : isCenter ? 4.4 : 3);
        context.globalAlpha = isFocus
          ? 0.9
          : isCenter && !lit.has(node.id)
            ? 0.55
            : 0.5;
        context.drawImage(
          glowFor(node.hue),
          (node.x ?? 0) - size / 2,
          (node.y ?? 0) - size / 2,
          size,
          size,
        );
      }

      // Artists.
      context.textAlign = 'center';
      context.textBaseline = 'middle';
      const ring = {
        selected: color('--md-on-surface'),
        center: color('--brand'),
        expanded: color('--md-outline'),
        base: color('--md-surface'),
      };
      for (const node of simNodes.current.values()) {
        const nx = node.x ?? 0;
        const ny = node.y ?? 0;
        const r = node.r;
        const age = (now - node.born) / FADE_MS;
        if (age < 1) animating = true;
        const dim = focused && !lit.has(node.id);
        // Dimmed, not gone: the shape of the whole web stays readable.
        const appear = Math.min(1, Math.max(0, age));
        const alpha = appear * (dim ? 0.3 : 1);
        // Arriving artists grow from 70% as they fade in.
        const grow = 0.7 + 0.3 * easeInOut(appear);
        const dr = r * grow;
        if (!dim) {
          context.globalAlpha = alpha * 0.6;
          context.drawImage(
            shadow(),
            nx - dr * 1.25,
            ny - dr * 1.15,
            dr * 2.5,
            dr * 2.5,
          );
        }
        context.globalAlpha = alpha;
        const photo = node.data.image ? photoFor(node.data.image) : null;
        const photoAlpha =
          photo?.state === 'ready'
            ? Math.min(1, (now - photo.readyAt) / PHOTO_FADE_MS)
            : 0;
        if (photoAlpha < 1) {
          context.drawImage(
            spriteFor(node.hue),
            nx - dr,
            ny - dr,
            dr * 2,
            dr * 2,
          );
          if (dr * k >= 9) {
            context.fillStyle = 'rgb(255 255 255 / 88%)';
            context.font = `700 ${Math.round(dr * 0.95)}px ${FONT_STACK}`;
            context.fillText(node.initial, nx, ny + dr * 0.04);
          }
        }
        if (photoAlpha > 0 && photo?.sprite) {
          if (photoAlpha < 1) animating = true;
          context.globalAlpha = alpha * photoAlpha;
          context.drawImage(photo.sprite, nx - dr, ny - dr, dr * 2, dr * 2);
          context.globalAlpha = alpha;
        }
        // A hairline in the page color keeps touching covers apart.
        context.beginPath();
        context.arc(nx, ny, dr, 0, 2 * Math.PI);
        context.lineWidth = 1.5 / zoomScale;
        context.strokeStyle = ring.base;
        context.stroke();
        const isCenter = node.id === center;
        const isSelected = node.id === selected;
        const isHovered = node.id === hoveredId;
        if (isCenter || isSelected || isHovered || node.data.expanded) {
          const gap = (isCenter || isSelected ? 3.5 : 2.5) / zoomScale;
          context.beginPath();
          context.arc(nx, ny, dr + gap, 0, 2 * Math.PI);
          context.lineWidth =
            (isSelected ? 3 : isCenter ? 3 : isHovered ? 2 : 1.25) / zoomScale;
          context.strokeStyle = isSelected
            ? ring.selected
            : isCenter
              ? ring.center
              : isHovered
                ? ring.selected
                : ring.expanded;
          context.stroke();
          // Selected and the start: a second, faint outer ring.
          if (isSelected || (isCenter && !focused)) {
            context.globalAlpha = alpha * 0.35;
            context.beginPath();
            context.arc(nx, ny, dr + gap + 4.5 / zoomScale, 0, 2 * Math.PI);
            context.lineWidth = 1 / zoomScale;
            context.stroke();
            context.globalAlpha = alpha;
          }
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
      const pill = color('--md-surface-container-high');
      placed.length = 0;
      // Orbit names only where there is room; on phones the chips name them.
      if (
        centerNode &&
        rings.current.length &&
        !focused &&
        width >= 600 &&
        k >= 0.6
      ) {
        context.font = ORBIT_FONT;
        context.textAlign = 'center';
        for (const ring of rings.current) {
          const text = props.current.describeOrbit(ring.orbit, ring.count);
          const sx = width / 2 + x + (centerNode.x ?? 0) * k;
          const sy = height / 2 + y + ((centerNode.y ?? 0) - ring.radius) * k;
          // Clear of the title and tools that float over the top of the canvas.
          if (sy < 130 || sy > height - 20) continue;
          const w = context.measureText(text).width + 18;
          const x0 = sx - w / 2;
          context.globalAlpha = 0.85;
          context.fillStyle = pill;
          context.beginPath();
          context.roundRect(x0, sy - 10, w, 20, 10);
          context.fill();
          context.globalAlpha = 1;
          context.fillStyle = quiet;
          context.fillText(text, sx, sy - 6);
          placed.push(x0, sy - 10, x0 + w, sy + 10);
        }
      }
      // Faces are obstacles too: a name never covers someone else's face.
      for (const node of simNodes.current.values()) {
        const nx = width / 2 + x + (node.x ?? 0) * k;
        const ny = height / 2 + y + (node.y ?? 0) * k;
        const nr = node.r * k + 2;
        placed.push(nx - nr, ny - nr, nx + nr, ny + nr);
      }
      const clear = (x0: number, y0: number, x1: number, y1: number) => {
        // A name cut off by the edge reads worse than no name.
        if (x0 < 4 || x1 > width - 4 || y0 < 4 || y1 > height - 4) return false;
        for (let i = 0; i < placed.length; i += 4)
          if (
            x0 < placed[i + 2]! &&
            x1 > placed[i]! &&
            y0 < placed[i + 3]! &&
            y1 > placed[i + 1]!
          )
            return false;
        return true;
      };
      candidates.length = 0;
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
                  : k >= LABEL_MIN_ZOOM
                    ? 4
                    : -1;
        if (rank >= 0) candidates.push({node, rank});
      }
      candidates.sort(
        (p, q) => p.rank - q.rank || q.node.weight - p.node.weight,
      );
      const cx = centerNode?.x ?? 0;
      const cy = centerNode?.y ?? 0;
      let drawn = 0;
      context.lineJoin = 'round';
      context.textAlign = 'left';
      for (const {node, rank} of candidates) {
        if (drawn >= MAX_LABELS) break;
        const strong = rank <= 1;
        const size = node.id === center ? LABEL_FONT + 2 : LABEL_FONT;
        const nx = width / 2 + x + (node.x ?? 0) * k;
        const ny = height / 2 + y + (node.y ?? 0) * k;
        if (nx < -80 || nx > width + 80 || ny < -40 || ny > height + 40)
          continue;
        const reach = node.r * k + 6;
        const w = node.labelWidth * (size / LABEL_FONT) + (strong ? 20 : 8);
        const h = size + (strong ? 10 : 6);
        // Names point away from the middle, the way a radial chart reads:
        // to the side for artists left and right of it, below or above for
        // the rest. Their ring neighbors sit along the ring, so this side is
        // the one most likely to be free.
        const below: [number, number] = [nx - w / 2, ny + reach - 4];
        const above: [number, number] = [nx - w / 2, ny - reach - h + 4];
        const right: [number, number] = [nx + reach, ny - h / 2];
        const left: [number, number] = [nx - reach - w, ny - h / 2];
        const dx = (node.x ?? 0) - cx;
        const dy = (node.y ?? 0) - cy;
        const side = dx >= 0 ? right : left;
        const vertical = dy >= 0 ? below : above;
        // Then the outward diagonal, then the far side, before giving up.
        const lean = reach * 0.6;
        const diagonal: [number, number] = [
          dx >= 0 ? nx + lean : nx - lean - w,
          dy >= 0 ? ny + lean : ny - lean - h,
        ];
        const otherSide = dx >= 0 ? left : right;
        const otherVertical = dy >= 0 ? above : below;
        const order =
          node.id === center
            ? [below]
            : Math.abs(dx) > Math.abs(dy) * 0.7
              ? [side, diagonal, vertical, otherVertical, otherSide]
              : [vertical, diagonal, side, otherSide, otherVertical];
        let spot = order.find(([x0, y0]) => clear(x0, y0, x0 + w, y0 + h));
        if (!spot) {
          if (!strong) continue;
          spot = order[0]!;
        }
        const [x0, y0] = spot;
        placed.push(x0, y0, x0 + w, y0 + h);
        drawn++;
        context.font =
          node.id === center
            ? LABEL_FONTS.center
            : strong || rank === 2
              ? LABEL_FONTS.strong
              : LABEL_FONTS.quiet;
        const tx = x0 + (strong ? 10 : 4);
        const ty = y0 + (strong ? 4 : 2);
        if (strong) {
          // The names that matter most sit on a pill, readable over anything.
          context.globalAlpha = 0.92;
          context.fillStyle = pill;
          context.beginPath();
          context.roundRect(x0, y0, w, h, h / 2);
          context.fill();
          context.globalAlpha = 1;
          context.fillStyle = ink;
          context.fillText(node.data.name, tx, ty);
          continue;
        }
        context.lineWidth = 4;
        context.strokeStyle = halo;
        context.strokeText(node.data.name, tx, ty);
        context.fillStyle = rank <= 2 ? ink : quiet;
        context.fillText(node.data.name, tx, ty);
      }

      // Keep animating while artists or photos are still fading in.
      if (animating && !frame.current)
        frame.current = requestAnimationFrame(draw);
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
      const from = {...transform.current};
      const to = {x: target.x, y: target.y, k: target.k};
      const started = performance.now();
      const step = (now: number) => {
        const t = Math.min(1, (now - started) / CAMERA_MS);
        const view = interpolateView(from, to, easeInOut(t));
        selection.call(
          behavior.transform,
          zoomIdentity.translate(view.x, view.y).scale(view.k),
        );
        cameraFrame.current = t < 1 ? requestAnimationFrame(step) : 0;
      };
      cameraFrame.current = requestAnimationFrame(step);
    }, []);

    const fit = useCallback(() => {
      const canvas = canvasRef.current;
      const list = [...simNodes.current.values()];
      if (!canvas || list.length === 0) return;
      const width = canvas.clientWidth;
      const height = canvas.clientHeight;
      if (width === 0 || height === 0) return;
      let minX = Infinity;
      let maxX = -Infinity;
      let minY = Infinity;
      let maxY = -Infinity;
      for (const node of list) {
        minX = Math.min(minX, (node.x ?? 0) - node.r);
        maxX = Math.max(maxX, (node.x ?? 0) + node.r);
        minY = Math.min(minY, (node.y ?? 0) - node.r);
        maxY = Math.max(maxY, (node.y ?? 0) + node.r + 20);
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
          MAX_FIT_ZOOM,
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

    /** Zooms about the middle of the screen. */
    const zoomBy = useCallback(
      (factor: number) => {
        const current = transform.current;
        const k = Math.max(0.2, Math.min(4, current.k * factor));
        const scale = k / current.k;
        moveCamera(
          zoomIdentity.translate(current.x * scale, current.y * scale).scale(k),
        );
        userMoved.current = true;
      },
      [moveCamera],
    );

    /** Centers the camera on an artist, zooming in a little if far out. */
    const focusOn = useCallback(
      (id: string, onlyIfHidden = false) => {
        const node = simNodes.current.get(id);
        const canvas = canvasRef.current;
        if (!node || !canvas) return;
        const {k, x, y} = transform.current;
        if (onlyIfHidden) {
          const sx = canvas.clientWidth / 2 + x + (node.x ?? 0) * k;
          const sy = canvas.clientHeight / 2 + y + (node.y ?? 0) * k;
          const margin = 72;
          if (
            sx > margin &&
            sx < canvas.clientWidth - margin &&
            sy > PADDING.top &&
            sy < canvas.clientHeight - PADDING.bottom
          )
            return;
        }
        const zoomTo = Math.max(k, 0.9);
        moveCamera(
          zoomIdentity
            .translate(-(node.x ?? 0) * zoomTo, -(node.y ?? 0) * zoomTo)
            .scale(zoomTo),
        );
        userMoved.current = true;
      },
      [moveCamera],
    );

    /** What is under a point given in canvas (CSS pixel) coordinates. */
    const hitTest = useCallback((px: number, py: number, slop = 6): Hit => {
      const canvas = canvasRef.current;
      if (!canvas) return null;
      const {k, x, y} = transform.current;
      const wx = (px - canvas.clientWidth / 2 - x) / k;
      const wy = (py - canvas.clientHeight / 2 - y) / k;
      let best: SimNode | null = null;
      let bestDistance = Infinity;
      for (const node of simNodes.current.values()) {
        const d = Math.hypot((node.x ?? 0) - wx, (node.y ?? 0) - wy) - node.r;
        if (d < bestDistance) {
          best = node;
          bestDistance = d;
        }
      }
      if (best && bestDistance < slop / k) return {kind: 'node', node: best};
      let nearest: SimLink | null = null;
      let nearestDistance = (slop + 1) / k;
      for (const link of simLinks.current) {
        const a = link.source as SimNode;
        const b = link.target as SimNode;
        const [p, q] = inward(a, b);
        const d = distanceToBow(wx, wy, p.x ?? 0, p.y ?? 0, q.x ?? 0, q.y ?? 0);
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
      const tipWidth = tip.offsetWidth;
      const tipHeight = tip.offsetHeight;
      const left = Math.max(
        8,
        Math.min(canvas.clientWidth - tipWidth - 8, px + 14),
      );
      const top =
        py + 18 + tipHeight > canvas.clientHeight - 8
          ? py - tipHeight - 12
          : py + 18;
      tip.style.transform = `translate(${Math.round(left)}px, ${Math.round(top)}px)`;
    }, []);

    // One-time setup: simulation, zoom, drag, theme tracking, resize, photos.
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
      // Orbits: direct connections of the start are held on their ring; artists
      // opened later drift to a bloom beyond the outer ring.
      let orbitNodes: SimNode[] = [];
      const orbitForce = Object.assign(
        (alpha: number) => {
          const start = simNodes.current.get(props.current.centerId ?? '');
          const ox = start?.x ?? 0;
          const oy = start?.y ?? 0;
          const outer = rings.current.at(-1)?.radius ?? FIRST_ORBIT;
          for (const node of orbitNodes) {
            if (node === start || (node.fx !== null && node.fx !== undefined))
              continue;
            const target = node.orbit
              ? (rings.current.find(r => r.orbit === node.orbit)?.radius ??
                outer)
              : outer + BLOOM_OFFSET;
            const strength = node.orbit ? ORBIT_STRENGTH : BLOOM_STRENGTH;
            const dx = (node.x ?? 0) - ox;
            const dy = (node.y ?? 0) - oy;
            const d = Math.hypot(dx, dy) || 1;
            // The bloom only pushes outward: free artists may wander further.
            if (!node.orbit && d > target) continue;
            const pull = ((target - d) / d) * strength * alpha;
            node.vx = (node.vx ?? 0) + dx * pull;
            node.vy = (node.vy ?? 0) + dy * pull;
            if (!node.orbit) continue;
            // Keep the top of the orbit clear for its name: slide artists
            // there sideways along the ring.
            const fromTop = Math.atan2(dx, -dy); // 0 at the top, + clockwise
            const clear = (ORBIT_LABEL_HALF + node.r) / target;
            if (Math.abs(fromTop) < clear) {
              const side = fromTop >= 0 ? 1 : -1;
              const push = (clear - Math.abs(fromTop)) * target * 0.25 * alpha;
              // The tangent, pointing clockwise.
              node.vx = (node.vx ?? 0) + (-dy / d) * push * side;
              node.vy = (node.vy ?? 0) + (dx / d) * push * side;
            }
          }
        },
        {
          initialize: (all: SimNode[]) => {
            orbitNodes = all;
          },
        },
      );
      const simulation = forceSimulation<SimNode, SimLink>()
        .force(
          'charge',
          // Artists on an orbit only need to spread along it; the rest push harder.
          forceManyBody<SimNode>()
            .strength(node => (node.orbit ? -45 : -190))
            .distanceMax(420),
        )
        .force(
          'collide',
          forceCollide<SimNode>(node => node.r + 9).strength(0.9),
        )
        .force('orbit', orbitForce)
        .force('x', forceX<SimNode>(0).strength(0.012))
        .force('y', forceY<SimNode>(0).strength(0.012))
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

      // d3-drag reports positions in the container (the canvas's wrapper, which
      // has the canvas's box) for mouse and touch alike; moves arrive as deltas
      // in screen pixels, turned into world units at the current zoom.
      const dragBehavior = drag<HTMLCanvasElement, unknown>()
        .subject(event => {
          const touch = String(event.sourceEvent?.type).startsWith('touch');
          const hit = hitTest(event.x, event.y, touch ? 14 : 6);
          // The start anchors the orbits: pressing it pans instead.
          return hit?.kind === 'node' && hit.node.id !== props.current.centerId
            ? hit.node
            : undefined;
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
          const k = transform.current.k;
          node.fx = (node.fx ?? node.x ?? 0) + event.dx / k;
          node.fy = (node.fy ?? node.y ?? 0) + event.dy / k;
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
      const stopPhotos = onPhotoReady(scheduleDraw);
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
        stopPhotos();
        colors.dispose();
        cancelAnimationFrame(frame.current);
        cancelAnimationFrame(cameraFrame.current);
        // Clear the handles: a stale one would make scheduleDraw think a frame
        // is still queued, and the web would never draw again (seen under
        // StrictMode, which runs this cleanup once right after mounting).
        frame.current = 0;
        cameraFrame.current = 0;
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
      // Each direct connection of the start gets an orbit by its kind.
      const orbits = new Map<string, Orbit>();
      for (const edge of edges) {
        if (edge.a !== centerId && edge.b !== centerId) continue;
        orbits.set(edge.a === centerId ? edge.b : edge.a, orbitOf(edge.kinds));
      }
      const now = performance.now();
      const isFirst = previous.size === 0;
      let added = 0;
      for (const node of nodes) {
        const strength = weights.get(node.id) ?? 0;
        const weight = weightOf(node, strength);
        const orbit = orbits.get(node.id) ?? null;
        const r = radiusOf(node, strength, node.id === centerId);
        // Start loading photos now, so they are often ready by the first frame.
        if (node.image) photoFor(node.image);
        const existing = previous.get(node.id);
        if (existing) {
          existing.data = node;
          existing.r = r;
          existing.weight = weight;
          existing.orbit = orbit;
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
          // The first web arrives in a ripple from the middle outward.
          born: isFirst ? now - FADE_MS + Math.min(added, 40) * 12 : now,
          labelWidth: 0,
          weight,
          orbit,
          x: (anchor?.x ?? 0) + Math.cos(angle) * distance,
          y: (anchor?.y ?? 0) + Math.sin(angle) * distance,
        });
      }
      // Orbit radii follow how many artists each holds, so they never crowd.
      const ringList: Ring[] = [];
      let inner = 0;
      for (const orbit of ORBITS) {
        const members = [...next.values()].filter(n => n.orbit === orbit);
        if (!members.length) continue;
        const around = members.reduce(
          (sum, n) => sum + 2 * n.r + ORBIT_SPACING,
          0,
        );
        // Rings pack outward from the first, so a ring of one sits close in.
        const radius = Math.max(
          inner ? inner + ORBIT_GAP : FIRST_ORBIT,
          around / (2 * Math.PI),
        );
        ringList.push({orbit, radius, count: members.length});
        inner = radius;
        // Newcomers on an orbit start on it, best known at the top and
        // alternating outward, so the eye lands on them first.
        const fresh = members
          .filter(n => !previous.has(n.id))
          .sort((p, q) => q.weight - p.weight);
        const taken = members.length - fresh.length;
        const step = (2 * Math.PI) / members.length;
        // A small per-orbit turn keeps the rings from lining up in spokes.
        const turn = ORBITS.indexOf(orbit) * 0.21;
        fresh.forEach((member, index) => {
          const i = index + taken;
          const side = i % 2 ? 1 : -1;
          // Half a step off the top, which stays clear for the orbit's name.
          const angle =
            -Math.PI / 2 + side * (Math.floor(i / 2) + 0.5) * step + turn;
          member.x = Math.cos(angle) * radius;
          member.y = Math.sin(angle) * radius;
        });
      }
      rings.current = ringList;
      const start = centerId ? next.get(centerId) : undefined;
      if (start) {
        start.fx = 0;
        start.fy = 0;
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
          .distance(l => 70 + 40 / (1 + l.data.strength))
          // Spokes from the start are held by the orbits, not by springs.
          .strength(l =>
            l.data.a === centerId || l.data.b === centerId
              ? 0
              : 0.3 + Math.min(0.4, l.data.strength / 20),
          ),
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
        zoomBy,
        focus(id: string) {
          focusOn(id);
        },
        snapshot(card: StoryCard) {
          const canvas = canvasRef.current;
          if (!canvas || simNodes.current.size === 0)
            return Promise.resolve(null);
          const start = simNodes.current.get(props.current.centerId ?? '');
          // Redraw now with nothing in focus, so the image shows the whole web.
          cancelAnimationFrame(frame.current);
          exporting.current = true;
          draw();
          cancelAnimationFrame(frame.current);
          frame.current = 0;
          // Crop to the artists (and their names), not the whole canvas.
          const ratio = canvas.width / (canvas.clientWidth || 1);
          const {k, x, y} = transform.current;
          let minX = Infinity;
          let maxX = -Infinity;
          let minY = Infinity;
          let maxY = -Infinity;
          for (const node of simNodes.current.values()) {
            const sx = canvas.clientWidth / 2 + x + (node.x ?? 0) * k;
            const sy = canvas.clientHeight / 2 + y + (node.y ?? 0) * k;
            const r = node.r * k;
            minX = Math.min(minX, sx - r - 48);
            maxX = Math.max(maxX, sx + r + 48);
            minY = Math.min(minY, sy - r - 16);
            maxY = Math.max(maxY, sy + r + 30);
          }
          const crop = {
            x: Math.max(0, minX) * ratio,
            y: Math.max(0, minY) * ratio,
            w: (Math.min(canvas.clientWidth, maxX) - Math.max(0, minX)) * ratio,
            h:
              (Math.min(canvas.clientHeight, maxY) - Math.max(0, minY)) * ratio,
          };
          const image = storyImage(canvas, crop, card, start?.hue ?? 350);
          exporting.current = false;
          scheduleDraw();
          return image;
        },
      }),
      [draw, fit, focusOn, scheduleDraw, zoomBy],
    );

    function localPoint(event: {clientX: number; clientY: number}) {
      const rect = canvasRef.current!.getBoundingClientRect();
      return [event.clientX - rect.left, event.clientY - rect.top] as const;
    }

    function announce(text: string) {
      if (liveRef.current) liveRef.current.textContent = text;
    }

    function open(id: string) {
      lastOpen.current = performance.now();
      props.current.onOpenNode(id);
    }

    function onKeyDown(event: KeyboardEvent<HTMLCanvasElement>) {
      const {selectedId: current, centerId: start} = props.current;
      const direction = ARROWS[event.key];
      if (direction) {
        event.preventDefault();
        const from = simNodes.current.get(current ?? start ?? '');
        if (!from) return;
        const target = current
          ? nearestInDirection(
              [...simNodes.current.values()].map(n => ({
                id: n.id,
                x: n.x ?? 0,
                y: n.y ?? 0,
              })),
              {id: from.id, x: from.x ?? 0, y: from.y ?? 0},
              direction[0],
              direction[1],
            )
          : from.id;
        if (!target) return;
        props.current.onSelectNode(target);
        focusOn(target, true);
        const node = simNodes.current.get(target);
        if (node) announce(props.current.describeNode(node.data));
        return;
      }
      switch (event.key) {
        case 'Enter':
          if (current) {
            event.preventDefault();
            open(current);
          }
          break;
        case 'Escape':
          if (current) {
            event.preventDefault();
            props.current.onSelectNode(null);
          }
          break;
        case 'Home':
          if (start) {
            event.preventDefault();
            props.current.onSelectNode(start);
            focusOn(start, true);
          }
          break;
        case '+':
        case '=':
          event.preventDefault();
          zoomBy(1.4);
          break;
        case '-':
          event.preventDefault();
          zoomBy(1 / 1.4);
          break;
        case '0':
          event.preventDefault();
          userMoved.current = false;
          fit();
          break;
      }
    }

    return (
      <div className="web__canvas">
        <canvas
          ref={canvasRef}
          role="img"
          aria-label={label}
          aria-describedby={helpId}
          tabIndex={0}
          data-node-count={nodes.length}
          onKeyDown={onKeyDown}
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
            const touch =
              (event.nativeEvent as PointerEvent).pointerType === 'touch';
            const hit = hitTest(...localPoint(event), touch ? 14 : 6);
            if (hit?.kind === 'node') {
              props.current.onSelectNode(hit.node.id);
              // A second tap on the same artist opens it (touch has no dblclick).
              if (touch) {
                const now = performance.now();
                const tap = lastTap.current;
                if (
                  tap &&
                  tap.id === hit.node.id &&
                  now - tap.at < DOUBLE_TAP_MS
                ) {
                  lastTap.current = null;
                  open(hit.node.id);
                } else lastTap.current = {id: hit.node.id, at: now};
              }
            } else if (hit?.kind === 'edge')
              props.current.onSelectEdge(
                (hit.link.source as SimNode).id,
                (hit.link.target as SimNode).id,
              );
            else props.current.onSelectNode(null);
          }}
          onDoubleClick={event => {
            // A double tap already opened it.
            if (performance.now() - lastOpen.current < 600) return;
            const hit = hitTest(...localPoint(event));
            if (hit?.kind === 'node') open(hit.node.id);
          }}
        />
        <p id={helpId} className="visually-hidden">
          {keyHelp}
        </p>
        <p ref={liveRef} className="visually-hidden" aria-live="polite" />
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
  context.font = LABEL_FONTS.strong;
  for (const node of nodes) {
    if (!node.labelWidth)
      node.labelWidth = context.measureText(node.data.name).width;
  }
  context.restore();
}

const ORBIT_FONT = `650 10.5px ${FONT_STACK}`;

/**
 * Lays the web out as a 1080x1920 story card: the subject's color as a wash,
 * the title, the web as drawn on screen, and the SongNexus name. Returns null
 * if the canvas can't be read (a photo served without CORS taints it).
 */
async function storyImage(
  web: HTMLCanvasElement,
  crop: {x: number; y: number; w: number; h: number},
  card: StoryCard,
  hue: number,
): Promise<Blob | null> {
  const W = 1080;
  const H = 1920;
  const out = document.createElement('canvas');
  out.width = W;
  out.height = H;
  const context = out.getContext('2d');
  if (!context || crop.w <= 0 || crop.h <= 0) return null;
  context.fillStyle = '#030303';
  context.fillRect(0, 0, W, H);
  const wash = context.createRadialGradient(W * 0.2, 0, 0, W * 0.2, 0, H * 0.9);
  wash.addColorStop(0, `hsl(${hue} 80% 45% / 55%)`);
  wash.addColorStop(1, `hsl(${hue} 80% 45% / 0%)`);
  context.fillStyle = wash;
  context.fillRect(0, 0, W, H);
  // The web, as large as fits between the title and the footer.
  const box = {x: 40, y: 380, w: W - 80, h: H - 380 - 220};
  const scale = Math.min(box.w / crop.w, box.h / crop.h, 2.4);
  const w = crop.w * scale;
  const h = crop.h * scale;
  context.imageSmoothingQuality = 'high';
  context.drawImage(
    web,
    crop.x,
    crop.y,
    crop.w,
    crop.h,
    box.x + (box.w - w) / 2,
    box.y + (box.h - h) / 2,
    w,
    h,
  );
  context.fillStyle = '#fff';
  context.textBaseline = 'alphabetic';
  context.font = `600 34px ${FONT_STACK}`;
  context.globalAlpha = 0.75;
  context.fillText(card.subtitle.toLocaleUpperCase(), 80, 200);
  context.globalAlpha = 1;
  context.font = `800 92px ${FONT_STACK}`;
  context.fillText(card.title, 80, 300, W - 160);
  // Footer: the mark (a red disc with a play triangle) and the name.
  context.fillStyle = '#ff0000';
  context.beginPath();
  context.arc(110, H - 120, 30, 0, 2 * Math.PI);
  context.fill();
  context.fillStyle = '#fff';
  context.beginPath();
  context.moveTo(100, H - 136);
  context.lineTo(100, H - 104);
  context.lineTo(127, H - 120);
  context.closePath();
  context.fill();
  context.font = `750 44px ${FONT_STACK}`;
  context.fillText(card.brand, 160, H - 104);
  return new Promise(resolve => {
    try {
      out.toBlob(blob => resolve(blob), 'image/png');
    } catch {
      // A tainted canvas can't be read back.
      resolve(null);
    }
  });
}
