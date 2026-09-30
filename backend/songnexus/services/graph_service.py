"""Graph use cases: neighborhoods, paths, evidence, centrality.

Route handlers call these methods; the methods call pure algorithms on the
current read model. Every query has hard limits (neighbors, depth, number of
alternative paths) so no request can trigger unbounded work.
"""

from __future__ import annotations

import time
from collections import Counter
from collections.abc import Iterable, Mapping
from itertools import pairwise

from songnexus.core.config import Settings
from songnexus.core.errors import InvalidRequestError, NotFoundError
from songnexus.core.metrics import metrics
from songnexus.graph import algorithms as alg
from songnexus.graph.projection import CATEGORIES, DEFAULT_CATEGORIES, ArtistGraph, kinds_for
from songnexus.readmodel import ReadModel, ReadModelStore
from songnexus.schemas import api
from songnexus.services.explain import KIND_LABELS, evidence_sentence, rank_evidence

EVIDENCE_PER_HOP = 3
# Exact Brandes betweenness is O(V*E); beyond this many nodes we sample pivots.
BETWEENNESS_EXACT_LIMIT = 800
BETWEENNESS_SAMPLE = 500


def parse_categories(raw: Iterable[str] | None) -> frozenset[str]:
    if not raw:
        return DEFAULT_CATEGORIES
    categories = frozenset(c.strip() for c in raw if c.strip())
    unknown = categories - set(CATEGORIES)
    if unknown:
        raise InvalidRequestError(f"unknown categories: {sorted(unknown)}", {"allowed": sorted(CATEGORIES)})
    return categories or DEFAULT_CATEGORIES


class GraphService:
    def __init__(self, store: ReadModelStore, settings: Settings) -> None:
        self._store = store
        self._settings = settings

    @property
    def model(self) -> ReadModel:
        return self._store.current

    # -- helpers ------------------------------------------------------------

    def _require(self, graph: ArtistGraph, artist_id: str) -> None:
        if artist_id not in graph.nodes:
            raise NotFoundError(f"artist {artist_id} not found", {"artist_id": artist_id})

    def path_node(self, graph: ArtistGraph, artist_id: str) -> api.PathNode:
        node = graph.nodes[artist_id]
        return api.PathNode(id=node.id, name=node.name, genres=list(node.genres))

    def evidence_items(
        self, graph: ArtistGraph, u: str, v: str, kinds: frozenset[str], limit: int | None
    ) -> tuple[list[api.EvidenceItem], int]:
        edge = graph.edge(u, v)
        if edge is None:
            return [], 0
        ranked = rank_evidence(graph, edge.evidence, kinds)
        chosen = ranked if limit is None else ranked[:limit]
        items = [
            api.EvidenceItem(
                kind=ev.kind,
                kind_label=KIND_LABELS[ev.kind],
                subject_type=ev.subject_type,
                subject_id=ev.subject_id,
                subject_title=graph.subject_titles.get(ev.subject_id),
                sentence=evidence_sentence(graph, edge, ev),
                roles={edge.a: ev.a_role, edge.b: ev.b_role},
            )
            for ev in chosen
        ]
        return items, len(ranked)

    def _path_out(
        self,
        graph: ArtistGraph,
        nodes: list[str],
        kinds: frozenset[str],
        adj: Mapping[str, Mapping[str, float]],
        cost: float | None,
    ) -> api.PathOut:
        hops = []
        for u, v in pairwise(nodes):
            items, total = self.evidence_items(graph, u, v, kinds, EVIDENCE_PER_HOP)
            hops.append(
                api.PathHop(source=u, target=v, strength=round(adj[u][v], 3), evidence=items, evidence_total=total)
            )
        return api.PathOut(
            nodes=[self.path_node(graph, n) for n in nodes],
            hops=hops,
            length=len(nodes) - 1,
            cost=round(cost, 4) if cost is not None else None,
        )

    # -- use cases ----------------------------------------------------------

    def neighborhood(
        self, artist_id: str, categories: frozenset[str], limit: int, depth: int, min_strength: float
    ) -> api.GraphPayload:
        model = self.model
        graph = model.graph
        self._require(graph, artist_id)
        if depth not in (1, 2):
            raise InvalidRequestError("depth must be 1 or 2")
        limit = max(1, min(limit, self._settings.max_neighbors))
        adj = graph.adjacency(kinds_for(categories))

        def top_neighbors(node: str, k: int) -> list[str]:
            nbrs = [(n, s) for n, s in adj[node].items() if s >= min_strength]
            nbrs.sort(key=lambda ns: (-ns[1], graph.nodes[ns[0]].name, ns[0]))
            return [n for n, _ in nbrs[:k]]

        total = sum(1 for s in adj[artist_id].values() if s >= min_strength)
        depth_of: dict[str, int] = {artist_id: 0}
        for n in top_neighbors(artist_id, limit):
            depth_of[n] = 1
        if depth == 2:
            # Spend the remaining node budget on the strongest first-degree
            # neighbors' own neighborhoods, keeping the view readable.
            budget = limit
            per_node = max(3, limit // max(1, len(depth_of) - 1))
            for n in [x for x, d in depth_of.items() if d == 1]:
                for nn in top_neighbors(n, per_node):
                    if budget <= 0:
                        break
                    if nn not in depth_of:
                        depth_of[nn] = 2
                        budget -= 1

        included = set(depth_of)
        edges = []
        for u in sorted(included):
            for v, strength in adj[u].items():
                if u < v and v in included and strength >= min_strength:
                    edge = graph.edge(u, v)
                    assert edge is not None
                    kinds = Counter(ev.kind for ev in edge.evidence if ev.kind in kinds_for(categories))
                    edges.append(api.GraphEdge(source=u, target=v, strength=round(strength, 3), kinds=dict(kinds)))
        nodes = [
            api.GraphNode(
                id=n,
                name=graph.nodes[n].name,
                hydrated=graph.nodes[n].hydrated,
                genres=list(graph.nodes[n].genres),
                degree=len(adj[n]),
                depth=d,
            )
            for n, d in sorted(depth_of.items(), key=lambda kv: (kv[1], graph.nodes[kv[0]].name))
        ]
        return api.GraphPayload(
            center=artist_id,
            nodes=nodes,
            edges=edges,
            truncated=total > limit,
            total_neighbors=total,
            categories=sorted(categories),
            graph_version=model.version,
        )

    def path(
        self, source: str, target: str, mode: str, categories: frozenset[str], max_depth: int, alternatives: int
    ) -> api.PathResponse:
        model = self.model
        graph = model.graph
        self._require(graph, source)
        self._require(graph, target)
        if not 1 <= max_depth <= self._settings.max_path_depth:
            raise InvalidRequestError(f"max_depth must be between 1 and {self._settings.max_path_depth}")
        if not 0 <= alternatives <= self._settings.max_alternative_paths:
            raise InvalidRequestError(f"alternatives must be between 0 and {self._settings.max_alternative_paths}")
        kinds = kinds_for(categories)
        adj = graph.adjacency(kinds)

        cache_key = ("path", source, target, mode, kinds, max_depth, alternatives)
        started = time.perf_counter()

        def compute() -> tuple[list[str] | None, float | None, list[list[str]], str]:
            if mode == "strongest":
                with metrics.timer("graph.path.dijkstra"):
                    result = alg.dijkstra_path(adj, source, target, max_depth=max_depth)
                algorithm = "dijkstra (cost = 1 / strength)"
            else:
                with metrics.timer("graph.path.bidirectional_bfs"):
                    result = alg.bidirectional_bfs_path(adj, source, target, max_depth=max_depth)
                algorithm = "bidirectional BFS"
            alts: list[list[str]] = []
            if alternatives and result.path is not None:
                with metrics.timer("graph.path.yen"):
                    ranked = alg.yen_k_shortest_paths(adj, source, target, alternatives + 1, max_depth)
                alts = [p for p in ranked if p != result.path][:alternatives]
                algorithm += f" + Yen k-shortest (k={alternatives + 1})"
            return result.path, result.cost, alts, algorithm

        path_nodes, cost, alts, algorithm = model.path_cache.get_or_compute(cache_key, compute)
        elapsed = round((time.perf_counter() - started) * 1000, 2)

        src, tgt = self.path_node(graph, source), self.path_node(graph, target)
        path_out = self._path_out(graph, path_nodes, kinds, adj, cost) if path_nodes else None
        if path_out is None:
            explanation = (
                f"No connection between {src.name} and {tgt.name} was found within {max_depth} steps "
                f"using {', '.join(sorted(categories))} relationships in the current dataset. "
                "This means the loaded data does not connect them, not that no real-world connection exists."
            )
        else:
            steps = "; then ".join(h.evidence[0].sentence for h in path_out.hops if h.evidence)
            plural = "s" if path_out.length != 1 else ""
            explanation = f"{src.name} and {tgt.name} are {path_out.length} step{plural} apart: {steps}."
        return api.PathResponse(
            found=path_out is not None,
            source=src,
            target=tgt,
            mode=mode,
            algorithm=algorithm,
            categories=sorted(categories),
            max_depth=max_depth,
            path=path_out,
            alternatives=[self._path_out(graph, p, kinds, adj, None) for p in alts],
            explanation=explanation,
            graph_version=model.version,
            elapsed_ms=elapsed,
        )

    def edge_evidence(self, a: str, b: str, categories: frozenset[str]) -> api.EdgeEvidenceResponse:
        model = self.model
        graph = model.graph
        self._require(graph, a)
        self._require(graph, b)
        kinds = kinds_for(categories)
        edge = graph.edge(a, b)
        if edge is None or edge.strength(kinds) == 0:
            raise NotFoundError("these artists are not directly connected", {"a": a, "b": b})
        items, _ = self.evidence_items(graph, a, b, kinds, limit=None)
        return api.EdgeEvidenceResponse(
            a=self.path_node(graph, a),
            b=self.path_node(graph, b),
            strength=round(edge.strength(kinds), 3),
            evidence=items,
            graph_version=model.version,
        )

    def warm(self, model: ReadModel) -> None:
        """Precompute default-category analytics so first requests are fast."""
        kinds = kinds_for(DEFAULT_CATEGORIES)
        for metric in ("pagerank", "betweenness", "degree"):
            self._centrality_scores(model, metric, kinds)

    def _centrality_scores(
        self, model: ReadModel, metric: str, kinds: frozenset[str]
    ) -> tuple[dict[str, float], str, bool]:
        adj = model.graph.adjacency(kinds)

        def compute() -> tuple[dict[str, float], str, bool]:
            with metrics.timer(f"graph.centrality.{metric}"):
                if metric == "pagerank":
                    return alg.pagerank(adj), "weighted PageRank (power iteration, d=0.85)", True
                if metric == "betweenness":
                    if len(adj) <= BETWEENNESS_EXACT_LIMIT:
                        return alg.betweenness(adj), "Brandes betweenness (exact)", True
                    return (
                        alg.betweenness(adj, sample_size=BETWEENNESS_SAMPLE, seed=0),
                        f"Brandes betweenness ({BETWEENNESS_SAMPLE} sampled pivots, seed 0)",
                        False,
                    )
                if metric == "weighted_degree":
                    return alg.weighted_degree(adj), "weighted degree (sum of strengths)", True
                return alg.degree(adj), "degree (distinct connected artists)", True

        return model.analytics_cache.get_or_compute(("centrality", metric, kinds), compute)

    def centrality(self, metric: str, categories: frozenset[str], limit: int, scope: str) -> api.CentralityResponse:
        model = self.model
        graph = model.graph
        limit = max(1, min(limit, 100))
        scores, algorithm, exact = self._centrality_scores(model, metric, kinds_for(categories))
        candidates = [n for n in scores if scope == "all" or graph.nodes[n].hydrated]
        candidates.sort(key=lambda n: (-scores[n], graph.nodes[n].name))
        results = [
            api.CentralityEntry(
                id=n,
                name=graph.nodes[n].name,
                score=round(scores[n], 6),
                rank=i + 1,
                genres=list(graph.nodes[n].genres),
            )
            for i, n in enumerate(candidates[:limit])
        ]
        return api.CentralityResponse(
            metric=metric,
            algorithm=algorithm,
            exact=exact,
            scope=scope,
            results=results,
            graph_version=model.version,
        )

    def stats(self) -> api.GraphStats:
        model = self.model
        adj = model.graph.adjacency(kinds_for(DEFAULT_CATEGORIES))
        components = model.analytics_cache.get_or_compute(("components",), lambda: alg.connected_components(adj))
        graph_stats = model.graph.stats()
        # Report connections as users see them by default (engineering-only links excluded).
        graph_stats["edges"] = sum(len(nbrs) for nbrs in adj.values()) // 2
        return api.GraphStats(
            graph_version=model.version,
            **graph_stats,
            components=len(components),
            largest_component=len(components[0]) if components else 0,
            built_at=model.built_at,
            build_ms=model.build_ms,
        )
