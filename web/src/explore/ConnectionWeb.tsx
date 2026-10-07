/**
 * The connection web, drawn on a canvas (SVG doesn't hold up past ~300 nodes).
 *
 * d3-force lays it out; d3-zoom pans and zooms; clicks are hit-tested against
 * nodes, then lines. The canvas is a visual aid: the list view next to it
 * carries the same content for keyboard and screen-reader users (AC-2.3).
 */
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
  useImperativeHandle,
  useRef,
} from 'react';

import {CATEGORY_ENCODING, dominantCategory} from '../components/encoding';

import type {WebEdge, WebNode} from './graphState';

interface SimNode extends SimulationNodeDatum {
  id: string;
  data: WebNode;
}

interface SimLink extends SimulationLinkDatum<SimNode> {
  data: WebEdge;
}

export interface ConnectionWebHandle {
  fit: () => void;
}

interface Props {
  nodes: WebNode[];
  edges: WebEdge[];
  centerId: string | null;
  selectedId: string | null;
  label: string;
  onSelectNode: (id: string) => void;
  onSelectEdge: (a: string, b: string) => void;
}

const nodeRadius = (node: SimNode, centerId: string | null) =>
  node.id === centerId ? 14 : node.data.expanded ? 10 : 7;
const lineWidth = (edge: WebEdge) =>
  Math.min(6, 1 + 1.2 * Math.log2(1 + edge.strength));

/** Resolves a CSS custom property (including light-dark()) to a concrete color. */
function resolveColors(element: HTMLElement): (variable: string) => string {
  const probe = document.createElement('span');
  probe.style.display = 'none';
  element.appendChild(probe);
  const cache = new Map<string, string>();
  return variable => {
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

export const ConnectionWeb = forwardRef<ConnectionWebHandle, Props>(
  (
    {nodes, edges, centerId, selectedId, label, onSelectNode, onSelectEdge},
    ref,
  ) => {
    const canvasRef = useRef<HTMLCanvasElement>(null);
    const simRef = useRef<Simulation<SimNode, SimLink> | null>(null);
    const simNodes = useRef(new Map<string, SimNode>());
    const simLinks = useRef<SimLink[]>([]);
    const transform = useRef<ZoomTransform>(zoomIdentity);
    const zoomRef = useRef<ZoomBehavior<HTMLCanvasElement, unknown> | null>(
      null,
    );
    const colorOf = useRef<(variable: string) => string>(() => '#888');
    const frame = useRef(0);
    const props = useRef({centerId, selectedId, onSelectNode, onSelectEdge});
    props.current = {centerId, selectedId, onSelectNode, onSelectEdge};

    const draw = useCallback(() => {
      frame.current = 0;
      const canvas = canvasRef.current;
      const context = canvas?.getContext('2d');
      if (!canvas || !context) return;
      const ratio = window.devicePixelRatio || 1;
      const {width, height} = canvas.getBoundingClientRect();
      if (
        canvas.width !== Math.round(width * ratio) ||
        canvas.height !== Math.round(height * ratio)
      ) {
        canvas.width = Math.round(width * ratio);
        canvas.height = Math.round(height * ratio);
      }
      const color = colorOf.current;
      const {k, x, y} = transform.current;
      context.setTransform(ratio, 0, 0, ratio, 0, 0);
      context.clearRect(0, 0, width, height);
      context.translate(width / 2 + x, height / 2 + y);
      context.scale(k, k);

      const selected = props.current.selectedId;
      for (const link of simLinks.current) {
        const a = link.source as SimNode;
        const b = link.target as SimNode;
        const encoding = CATEGORY_ENCODING[dominantCategory(link.data.kinds)];
        const highlighted =
          selected !== null && (a.id === selected || b.id === selected);
        context.globalAlpha = selected === null || highlighted ? 0.85 : 0.18;
        context.strokeStyle = color(encoding.color);
        context.lineWidth = lineWidth(link.data) / Math.sqrt(k);
        context.setLineDash(encoding.dash.map(d => d / Math.sqrt(k)));
        context.beginPath();
        context.moveTo(a.x ?? 0, a.y ?? 0);
        context.lineTo(b.x ?? 0, b.y ?? 0);
        context.stroke();
      }
      context.setLineDash([]);
      context.globalAlpha = 1;

      const fontSize = 12 / Math.sqrt(k);
      context.font = `500 ${fontSize}px system-ui, sans-serif`;
      context.textAlign = 'center';
      for (const node of simNodes.current.values()) {
        const radius = nodeRadius(node, props.current.centerId);
        const isSelected = node.id === selected;
        context.beginPath();
        context.arc(node.x ?? 0, node.y ?? 0, radius, 0, 2 * Math.PI);
        context.fillStyle = color(
          node.id === props.current.centerId || isSelected
            ? '--md-primary'
            : '--md-surface-container-highest',
        );
        context.fill();
        context.lineWidth = isSelected ? 3 / Math.sqrt(k) : 1.5 / Math.sqrt(k);
        context.strokeStyle = color(
          isSelected ? '--md-on-surface' : '--md-outline',
        );
        context.stroke();
        // Labels: always for expanded nodes; for others once zoomed in enough.
        if (node.data.expanded || k > 1.4 || isSelected) {
          context.fillStyle = color('--md-on-surface');
          context.strokeStyle = color('--md-surface');
          context.lineWidth = 3 / Math.sqrt(k);
          const ty = (node.y ?? 0) + radius + fontSize + 2;
          context.strokeText(node.data.name, node.x ?? 0, ty);
          context.fillText(node.data.name, node.x ?? 0, ty);
        }
      }
    }, []);

    const scheduleDraw = useCallback(() => {
      if (!frame.current) frame.current = requestAnimationFrame(draw);
    }, [draw]);

    // One-time setup: simulation, zoom, theme tracking, resize.
    useEffect(() => {
      const canvas = canvasRef.current!;
      colorOf.current = resolveColors(canvas.parentElement ?? document.body);
      const simulation = forceSimulation<SimNode, SimLink>()
        .force(
          'charge',
          forceManyBody<SimNode>().strength(-160).distanceMax(500),
        )
        .force('collide', forceCollide<SimNode>(18))
        .force('x', forceX<SimNode>(0).strength(0.04))
        .force('y', forceY<SimNode>(0).strength(0.04))
        .on('tick', scheduleDraw);
      if (window.matchMedia('(prefers-reduced-motion: reduce)').matches)
        simulation.alphaDecay(0.2);
      simRef.current = simulation;

      const zoomBehavior = zoom<HTMLCanvasElement, unknown>()
        .scaleExtent([0.2, 5])
        .on('zoom', event => {
          transform.current = event.transform as ZoomTransform;
          scheduleDraw();
        });
      select(canvas).call(zoomBehavior).on('dblclick.zoom', null);
      zoomRef.current = zoomBehavior;

      const refreshColors = () => {
        colorOf.current = resolveColors(canvas.parentElement ?? document.body);
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

      return () => {
        simulation.stop();
        themeObserver.disconnect();
        media.removeEventListener('change', refreshColors);
        resize.disconnect();
        cancelAnimationFrame(frame.current);
      };
    }, [scheduleDraw]);

    // Data changes: keep positions of known nodes, seed new ones near their neighbor.
    useEffect(() => {
      const simulation = simRef.current;
      if (!simulation) return;
      const previous = simNodes.current;
      const next = new Map<string, SimNode>();
      for (const node of nodes) {
        const existing = previous.get(node.id);
        if (existing) {
          existing.data = node;
          next.set(node.id, existing);
        } else {
          const anchor = edges.find(e => e.a === node.id || e.b === node.id);
          const neighbor = anchor
            ? previous.get(anchor.a === node.id ? anchor.b : anchor.a)
            : undefined;
          next.set(node.id, {
            id: node.id,
            data: node,
            x: (neighbor?.x ?? 0) + (Math.random() - 0.5) * 40,
            y: (neighbor?.y ?? 0) + (Math.random() - 0.5) * 40,
          });
        }
      }
      simNodes.current = next;
      simLinks.current = edges
        .filter(e => next.has(e.a) && next.has(e.b))
        .map(e => ({source: next.get(e.a)!, target: next.get(e.b)!, data: e}));
      simulation.nodes([...next.values()]);
      simulation.force(
        'link',
        forceLink<SimNode, SimLink>(simLinks.current)
          .id(n => n.id)
          .distance(l => 60 + 40 / (1 + l.data.strength)),
      );
      simulation.alpha(0.8).restart();
    }, [nodes, edges]);

    useEffect(scheduleDraw, [selectedId, centerId, scheduleDraw]);

    useImperativeHandle(
      ref,
      () => ({
        fit() {
          const canvas = canvasRef.current;
          const list = [...simNodes.current.values()];
          if (!canvas || !zoomRef.current || list.length === 0) return;
          const xs = list.map(n => n.x ?? 0);
          const ys = list.map(n => n.y ?? 0);
          const {width, height} = canvas.getBoundingClientRect();
          const spanX = Math.max(...xs) - Math.min(...xs) + 80;
          const spanY = Math.max(...ys) - Math.min(...ys) + 80;
          const k = Math.max(
            0.2,
            Math.min(2, Math.min(width / spanX, height / spanY)),
          );
          const cx = (Math.max(...xs) + Math.min(...xs)) / 2;
          const cy = (Math.max(...ys) + Math.min(...ys)) / 2;
          select(canvas).call(
            zoomRef.current.transform,
            zoomIdentity.translate(-cx * k, -cy * k).scale(k),
          );
        },
      }),
      [],
    );

    return (
      <canvas
        ref={canvasRef}
        role="img"
        aria-label={label}
        style={{
          inlineSize: '100%',
          blockSize: '100%',
          touchAction: 'none',
          cursor: 'grab',
        }}
        onClick={event => {
          const canvas = canvasRef.current!;
          const rect = canvas.getBoundingClientRect();
          const {k, x, y} = transform.current;
          const px = (event.clientX - rect.left - rect.width / 2 - x) / k;
          const py = (event.clientY - rect.top - rect.height / 2 - y) / k;
          let best: SimNode | null = null;
          let bestDistance = Infinity;
          for (const node of simNodes.current.values()) {
            const d =
              Math.hypot((node.x ?? 0) - px, (node.y ?? 0) - py) -
              nodeRadius(node, props.current.centerId);
            if (d < bestDistance) {
              best = node;
              bestDistance = d;
            }
          }
          if (best && bestDistance < 8 / k) {
            props.current.onSelectNode(best.id);
            return;
          }
          for (const link of simLinks.current) {
            const a = link.source as SimNode;
            const b = link.target as SimNode;
            if (
              distanceToSegment(
                px,
                py,
                a.x ?? 0,
                a.y ?? 0,
                b.x ?? 0,
                b.y ?? 0,
              ) <
              6 / k
            ) {
              props.current.onSelectEdge(a.id, b.id);
              return;
            }
          }
        }}
      />
    );
  },
);
