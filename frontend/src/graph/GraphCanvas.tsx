import { drag } from "d3-drag";
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
} from "d3-force";
import { select, type Selection as D3Selection } from "d3-selection";
import { zoom, zoomIdentity, type ZoomBehavior } from "d3-zoom";
import { useCallback, useEffect, useRef, useState } from "react";

import { dominantKind, edgeKey, type PathOverlay, type Selection, type VisEdge, type VisNode } from "../state/graphState";
import { FitIcon } from "../components/Icons";
import { Swatch } from "../components/Swatch";
import { ALL_CATEGORIES, type Category } from "../types/api";
import { CATEGORY_ENCODING, CATEGORY_LABELS, kindEncoding } from "../utils/format";

interface SimNode extends SimulationNodeDatum {
  id: string;
  data: VisNode;
}

interface SimLink extends SimulationLinkDatum<SimNode> {
  key: string;
  data: VisEdge;
}

interface Props {
  nodes: VisNode[];
  edges: VisEdge[];
  centerId: string | null;
  selection: Selection;
  path: PathOverlay | null;
  onSelectNode: (id: string) => void;
  onExpandNode: (id: string) => void;
  onSelectEdge: (a: string, b: string) => void;
  categories: Category[];
  onClearPath: () => void;
}

const radius = (n: VisNode) => Math.min(16, 4 + 1.4 * Math.sqrt(n.degree)) + (n.hydrated ? 3 : 0);
const strokeWidth = (e: VisEdge) => Math.min(7, 1 + 1.4 * Math.log2(1 + e.strength));

export function GraphCanvas({
  nodes,
  edges,
  centerId,
  selection,
  path,
  onSelectNode,
  onExpandNode,
  onSelectEdge,
  categories,
  onClearPath,
}: Props) {
  const svgRef = useRef<SVGSVGElement | null>(null);
  const simRef = useRef<Simulation<SimNode, SimLink> | null>(null);
  const positions = useRef(new Map<string, { x: number; y: number }>());
  const zoomRef = useRef<ZoomBehavior<SVGSVGElement, unknown> | null>(null);
  const handlers = useRef({ onSelectNode, onExpandNode, onSelectEdge });
  const [hover, setHover] = useState<{ node: VisNode; x: number; y: number } | null>(null);

  useEffect(() => {
    handlers.current = { onSelectNode, onExpandNode, onSelectEdge };
  }, [onSelectNode, onExpandNode, onSelectEdge]);

  // One-time setup: layers, zoom, and the simulation.
  useEffect(() => {
    const svg = select(svgRef.current!);
    const root = svg.append("g").attr("class", "graph-root");
    root.append("g").attr("class", "links");
    root.append("g").attr("class", "nodes");
    // Labels live in their own top layer so no circle can cover them.
    root.append("g").attr("class", "labels");
    const zoomBehavior = zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.2, 4])
      .on("zoom", (event) => root.attr("transform", event.transform.toString()));
    svg.call(zoomBehavior).on("dblclick.zoom", null);
    zoomRef.current = zoomBehavior;

    const sim = forceSimulation<SimNode, SimLink>()
      .force("charge", forceManyBody<SimNode>().strength(-420).distanceMax(700))
      .force(
        "link",
        forceLink<SimNode, SimLink>()
          .id((d) => d.id)
          .distance((l) => 70 + 50 / Math.max(1, l.data.strength))
          .strength(0.6),
      )
      .force("collide", forceCollide<SimNode>((d) => radius(d.data) + 6))
      .force("x", forceX(0).strength(0.04))
      .force("y", forceY(0).strength(0.04))
      .alphaDecay(0.035);
    sim.on("tick", () => {
      root
        .select<SVGGElement>("g.links")
        .selectAll<SVGGElement, SimLink>("g.link")
        .selectAll<SVGLineElement, SimLink>("line")
        .attr("x1", (d) => (d.source as SimNode).x ?? 0)
        .attr("y1", (d) => (d.source as SimNode).y ?? 0)
        .attr("x2", (d) => (d.target as SimNode).x ?? 0)
        .attr("y2", (d) => (d.target as SimNode).y ?? 0);
      root
        .select<SVGGElement>("g.nodes")
        .selectAll<SVGGElement, SimNode>("g.node")
        .attr("transform", (d) => {
          positions.current.set(d.id, { x: d.x ?? 0, y: d.y ?? 0 });
          return `translate(${d.x ?? 0},${d.y ?? 0})`;
        });
      root
        .select<SVGGElement>("g.labels")
        .selectAll<SVGTextElement, SimNode>("text.label")
        .attr("x", (d) => (d.x ?? 0) + radius(d.data) + 4)
        .attr("y", (d) => d.y ?? 0);
    });
    simRef.current = sim;

    const resize = () => {
      const { width, height } = svgRef.current!.getBoundingClientRect();
      svg.attr("viewBox", `${-width / 2} ${-height / 2} ${width} ${height}`);
    };
    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(svgRef.current!);
    return () => {
      observer.disconnect();
      sim.stop();
      root.remove();
    };
  }, []);

  // Data updates: keep existing positions, place new nodes next to a known neighbor.
  useEffect(() => {
    const sim = simRef.current;
    if (!sim) return;
    const byId = new Map<string, SimNode>();
    const neighborOf = new Map<string, string>();
    for (const e of edges) {
      if (!neighborOf.has(e.target)) neighborOf.set(e.target, e.source);
      if (!neighborOf.has(e.source)) neighborOf.set(e.source, e.target);
    }
    const simNodes = nodes.map((n) => {
      const known = positions.current.get(n.id) ?? positions.current.get(neighborOf.get(n.id) ?? "");
      const jitter = () => (Math.random() - 0.5) * 40;
      const node: SimNode = { id: n.id, data: n, x: (known?.x ?? 0) + jitter(), y: (known?.y ?? 0) + jitter() };
      if (positions.current.has(n.id)) {
        node.x = known!.x;
        node.y = known!.y;
      }
      byId.set(n.id, node);
      return node;
    });
    const simLinks: SimLink[] = edges
      .filter((e) => byId.has(e.source) && byId.has(e.target))
      .map((e) => ({ key: e.key, data: e, source: e.source, target: e.target }));

    const svg = select(svgRef.current!);
    const linkGroups = svg
      .select<SVGGElement>("g.links")
      .selectAll<SVGGElement, SimLink>("g.link")
      .data(simLinks, (d) => d.key)
      .join((enter) => {
        const g = enter.append("g").attr("class", "link");
        g.append("line").attr("class", "link-hit");
        g.append("line").attr("class", "link-line");
        return g;
      });
    linkGroups
      .select<SVGLineElement>("line.link-line")
      .attr("stroke", (d) => kindEncoding(dominantKind(d.data)).color)
      .attr("stroke-dasharray", (d) => kindEncoding(dominantKind(d.data)).dash)
      .attr("stroke-width", (d) => strokeWidth(d.data));
    linkGroups.on("click", (event, d) => {
      event.stopPropagation();
      handlers.current.onSelectEdge(d.data.source, d.data.target);
    });

    const nodeGroups = svg
      .select<SVGGElement>("g.nodes")
      .selectAll<SVGGElement, SimNode>("g.node")
      .data(simNodes, (d) => d.id)
      .join((enter) => {
        const g = enter.append("g").attr("class", "node");
        g.append("circle");
        return g;
      });
    nodeGroups
      .select("circle")
      .attr("r", (d) => radius(d.data))
      .classed("seed", (d) => d.data.hydrated);
    svg
      .select<SVGGElement>("g.labels")
      .selectAll<SVGTextElement, SimNode>("text.label")
      .data(simNodes, (d) => d.id)
      .join((enter) => enter.append("text").attr("class", "label").attr("dy", "0.35em"))
      .text((d) => d.data.name);
    nodeGroups
      .on("click", (event, d) => {
        event.stopPropagation();
        handlers.current.onSelectNode(d.id);
      })
      .on("dblclick", (event, d) => {
        event.stopPropagation();
        handlers.current.onExpandNode(d.id);
      })
      .on("mouseenter", (event: MouseEvent, d) => {
        setHover({ node: d.data, x: event.offsetX, y: event.offsetY });
        svg.selectAll<SVGTextElement, SimNode>("text.label").classed("hovered", (l) => l.id === d.id);
      })
      .on("mouseleave", () => {
        setHover(null);
        svg.selectAll("text.label").classed("hovered", false);
      });
    nodeGroups.call(
      drag<SVGGElement, SimNode>()
        .on("start", (event, d) => {
          if (!event.active) sim.alphaTarget(0.2).restart();
          d.fx = d.x;
          d.fy = d.y;
        })
        .on("drag", (event, d) => {
          d.fx = event.x;
          d.fy = event.y;
        })
        .on("end", (event, d) => {
          if (!event.active) sim.alphaTarget(0);
          d.fx = null;
          d.fy = null;
        }),
    );

    sim.nodes(simNodes);
    sim.force<ReturnType<typeof forceLink<SimNode, SimLink>>>("link")!.links(simLinks);
    sim.alpha(0.7).restart();
  }, [nodes, edges]);

  // Highlight state only changes classes; the layout keeps running untouched.
  useEffect(() => {
    const svg = select(svgRef.current!);
    const pathNodes = new Set(path?.nodes ?? []);
    const pathEdges = new Set(path?.edgeKeys ?? []);
    const selectedEdge = selection?.kind === "edge" ? edgeKey(selection.a, selection.b) : null;
    const selectedNode = selection?.kind === "artist" ? selection.id : null;
    svg.classed("has-path", pathNodes.size > 0);
    const labelled = labelledNodes(nodes, centerId, pathNodes, selectedNode);
    (svg.selectAll("g.node") as D3Selection<SVGGElement, SimNode, SVGGElement, unknown>)
      .classed("center", (d) => d.id === centerId)
      .classed("selected", (d) => d.id === selectedNode)
      .classed("on-path", (d) => pathNodes.has(d.id));
    (svg.selectAll("text.label") as D3Selection<SVGTextElement, SimNode, SVGGElement, unknown>)
      .classed("labelled", (d) => labelled.has(d.id))
      .classed("on-path", (d) => pathNodes.has(d.id));
    // Edges touching the focused artist carry the story; the rest is context.
    const focus = selectedNode ?? centerId;
    (svg.selectAll("g.link") as D3Selection<SVGGElement, SimLink, SVGGElement, unknown>)
      .classed("on-path", (d) => pathEdges.has(d.key))
      .classed("selected", (d) => d.key === selectedEdge)
      .classed("focus", (d) => d.data.source === focus || d.data.target === focus);
  }, [nodes, edges, centerId, selection, path]);

  const fit = useCallback(() => {
    const svg = svgRef.current;
    if (!svg || !zoomRef.current) return;
    const points = [...positions.current.values()];
    if (!points.length) return;
    const xs = points.map((p) => p.x);
    const ys = points.map((p) => p.y);
    const { width, height } = svg.getBoundingClientRect();
    // Generous padding leaves room for labels and the floating buttons.
    const spanX = Math.max(...xs) - Math.min(...xs) + 240;
    const spanY = Math.max(...ys) - Math.min(...ys) + 160;
    const scale = Math.min(1.2, Math.max(0.2, Math.min(width / spanX, height / spanY)));
    const cx = (Math.max(...xs) + Math.min(...xs)) / 2;
    const cy = (Math.max(...ys) + Math.min(...ys)) / 2;
    select(svg).call(zoomRef.current.transform, zoomIdentity.scale(scale).translate(-cx, -cy));
  }, []);

  // A newly highlighted path may reach far outside the view: refit once the layout settles.
  useEffect(() => {
    if (!path) return;
    const timer = window.setTimeout(fit, 1400);
    return () => window.clearTimeout(timer);
  }, [path, fit]);

  return (
    <div className="graph-canvas">
      <svg ref={svgRef} role="img" aria-label="Artist connection graph" />
      <div className="graph-toolbar">
        <div>
          {path && (
            <button type="button" className="btn btn-float" onClick={onClearPath}>
              Clear highlighted path
            </button>
          )}
        </div>
        <button type="button" className="btn btn-float" onClick={fit} title="Fit graph to view">
          <FitIcon size={14} /> Fit
        </button>
      </div>
      <Legend categories={categories} hasPath={path !== null} />
      {hover && (
        <div className="graph-tooltip" style={{ left: hover.x + 14, top: hover.y + 14 }}>
          <strong>{hover.node.name}</strong>
          {hover.node.genres.length > 0 && <span className="genres">{hover.node.genres.slice(0, 3).join(" · ")}</span>}
          <span className="hint">
            {hover.node.degree.toLocaleString()} connections · {hover.node.expanded ? "expanded" : "double-click to expand"}
          </span>
        </div>
      )}
    </div>
  );
}

/** Legend: line color and dash identify connection types; node fill identifies coverage. */
function Legend({ categories, hasPath }: { categories: Category[]; hasPath: boolean }) {
  // Collapsed by default on narrow screens, where it would cover the graph.
  const [open, setOpen] = useState(() => window.matchMedia("(min-width: 901px)").matches);
  return (
    <div className="graph-legend" aria-label="Legend">
      <button type="button" className="legend-toggle" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        Legend {open ? "▾" : "▸"}
      </button>
      {open && (
        <>
          <div className="legend-row">
            {ALL_CATEGORIES.filter((c) => categories.includes(c)).map((c) => (
              <span className="legend-item" key={c}>
                <Swatch encoding={CATEGORY_ENCODING[c]} />
                {CATEGORY_LABELS[c]}
              </span>
            ))}
          </div>
          <div className="legend-row">
            <span className="legend-item">
              <span className="legend-dot seed" /> Full discography loaded
            </span>
            <span className="legend-item">
              <span className="legend-dot credited" /> Known from credits
            </span>
            {hasPath && (
              <span className="legend-item">
                <span className="legend-dot path" /> On the path
              </span>
            )}
          </div>
        </>
      )}
    </div>
  );
}

/** Label only what helps orientation: seeds, the center, the path, the selection, and the biggest hubs. */
function labelledNodes(nodes: VisNode[], centerId: string | null, pathNodes: Set<string>, selected: string | null) {
  const hubs = [...nodes].sort((a, b) => b.degree - a.degree).slice(0, 12);
  const ids = new Set<string>(hubs.map((n) => n.id));
  for (const n of nodes) if (n.hydrated) ids.add(n.id);
  for (const id of pathNodes) ids.add(id);
  if (centerId) ids.add(centerId);
  if (selected) ids.add(selected);
  return ids;
}
