"""Artist embeddings: FastRP over credits, co-listening and genres.

Each artist gets a dense unit vector such that artists close in the graph are
close in the space. The graph has three kinds of edges:

- **credits**: the collaboration graph (who made music with whom), weighted by
  the strength of the connection;
- **co-listening**: aggregate "played in the same sessions" lists, weighted by
  rank (1/sqrt(rank)), at most ``COLISTEN_TOP`` per artist;
- **genres**: each artist is linked to a node per genre with its vote share,
  so two artists with similar genre mixes meet through the genre nodes.

The method is FastRP (Chen et al., "Fast and Accurate Network Embeddings via
Very Sparse Random Projection", CIKM 2019): a very sparse random projection of
each node, propagated over the degree-normalized graph a few hops, each hop
row-normalized and summed with fixed weights. It needs no training, runs in
seconds for this catalog and is deterministic for a seed. It is the retrieval
space and a diversity metric; the ranker learns what to do with similarity.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

DIMENSIONS = 64
HOP_WEIGHTS = (0.0, 0.6, 1.0, 1.0)  # weights of hops 1..4 (hop 1 alone is too local)
DEGREE_POWER = -0.5  # tempers popular hubs (FastRP's beta)
SPARSITY = 3  # Achlioptas: entries are +-sqrt(3) with probability 1/6 each
COLISTEN_TOP = 30
COLISTEN_WEIGHT = 1.0
GENRE_WEIGHT = 0.6
GENRE_PREFIX = "genre:"


@dataclass(frozen=True, eq=False)
class Embeddings:
    """Unit vectors for artists, one row per artist.

    Attributes:
        ids: Artist IDs in row order.
        matrix: ``len(ids) x dimensions``, every row unit length (or zero).
        version: The catalog version the space was built for.
    """

    ids: tuple[str, ...]
    matrix: NDArray[np.float32]
    version: str

    def __post_init__(self) -> None:
        """Indexes rows by artist ID."""
        object.__setattr__(self, "_row", {a: i for i, a in enumerate(self.ids)})

    def row(self, artist_id: str) -> int | None:
        """The row of an artist, or None when it has no vector."""
        return self._row.get(artist_id)  # type: ignore[attr-defined, no-any-return]

    def vector(self, artist_id: str) -> NDArray[np.float32] | None:
        """An artist's unit vector, or None."""
        i = self.row(artist_id)
        return None if i is None else self.matrix[i]

    def mean(self, weights: Mapping[str, float]) -> NDArray[np.float32] | None:
        """The normalized weighted mean of some artists' vectors (None if none have one)."""
        rows = [(self.row(a), w) for a, w in weights.items()]
        rows = [(i, w) for i, w in rows if i is not None and w > 0]
        if not rows:
            return None
        idx = np.array([i for i, _ in rows])
        w = np.array([w for _, w in rows], dtype=np.float32)
        v = (self.matrix[idx] * w[:, None]).sum(axis=0)
        norm = float(np.linalg.norm(v))
        return None if norm == 0 else (v / norm).astype(np.float32)

    def similarity(self, a: str, b: str) -> float:
        """Cosine similarity of two artists (0 when either has no vector)."""
        va, vb = self.vector(a), self.vector(b)
        if va is None or vb is None:
            return 0.0
        return float(va @ vb)

    def to_payload(self) -> dict[str, object]:
        """A JSON-safe form for storage (rounded to 4 decimals)."""
        return {
            "version": self.version,
            "dimensions": int(self.matrix.shape[1]) if self.matrix.size else DIMENSIONS,
            "ids": list(self.ids),
            "rows": np.round(self.matrix, 4).tolist(),
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> Embeddings:
        """Reads ``to_payload`` output."""
        ids = tuple(str(a) for a in payload["ids"])  # type: ignore[attr-defined]
        rows = payload["rows"]
        dims = int(payload.get("dimensions", DIMENSIONS))  # type: ignore[call-overload]
        matrix = (
            np.asarray(rows, dtype=np.float32) if ids else np.zeros((0, dims), dtype=np.float32)
        )
        return cls(ids=ids, matrix=matrix, version=str(payload["version"]))


def build_edges(
    adjacency: Mapping[str, Mapping[str, float]],
    colistening: Mapping[str, Mapping[str, int]],
    genres: Mapping[str, Iterable[tuple[str, float]]],
) -> dict[str, dict[str, float]]:
    """The symmetric weighted graph FastRP propagates over.

    Args:
        adjacency: Collaboration strength between artists.
        colistening: Artist -> {other artist: rank}, 1 = most co-listened.
        genres: Artist -> (genre ID, share) pairs.
    """
    edges: dict[str, dict[str, float]] = defaultdict(dict)

    def link(u: str, v: str, w: float) -> None:
        if u == v or w <= 0:
            return
        edges[u][v] = edges[u].get(v, 0.0) + w
        edges[v][u] = edges[v].get(u, 0.0) + w

    for u, nbrs in adjacency.items():
        for v, w in nbrs.items():
            if u < v:
                link(u, v, math.log1p(w))
    for u, ranked in colistening.items():
        for v, rank in sorted(ranked.items(), key=lambda kv: kv[1])[:COLISTEN_TOP]:
            link(u, v, COLISTEN_WEIGHT / math.sqrt(max(rank, 1)))
    for artist, shares in genres.items():
        for genre_id, share in shares:
            link(artist, GENRE_PREFIX + genre_id, GENRE_WEIGHT * share)
    for u in adjacency:
        edges.setdefault(u, {})
    return dict(edges)


def fastrp(
    edges: Mapping[str, Mapping[str, float]],
    *,
    dimensions: int = DIMENSIONS,
    seed: int = 7,
) -> tuple[list[str], NDArray[np.float32]]:
    """FastRP embeddings for every node of ``edges`` (nodes sorted, rows unit length)."""
    nodes = sorted(edges)
    if not nodes:
        return [], np.zeros((0, dimensions), dtype=np.float32)
    index = {n: i for i, n in enumerate(nodes)}
    rows, cols, vals = [], [], []
    for u, nbrs in edges.items():
        for v, w in nbrs.items():
            rows.append(index[u])
            cols.append(index[v])
            vals.append(w)
    n = len(nodes)
    r_idx = np.asarray(rows, dtype=np.int64)
    c_idx = np.asarray(cols, dtype=np.int64)
    w_arr = np.asarray(vals, dtype=np.float64)
    degree = np.bincount(r_idx, weights=w_arr, minlength=n)
    degree[degree == 0] = 1.0
    # Row-normalized transition weights: S = D^-1 A.
    w_norm = w_arr / degree[r_idx]

    rng = np.random.default_rng(seed)
    draw = rng.random((n, dimensions))
    scale = math.sqrt(SPARSITY)
    projection = np.where(
        draw < 1 / (2 * SPARSITY), scale, np.where(draw < 1 / SPARSITY, -scale, 0.0)
    )
    projection *= np.power(degree, DEGREE_POWER)[:, None]

    def propagate(m: NDArray[np.float64]) -> NDArray[np.float64]:
        out = np.zeros_like(m)
        np.add.at(out, r_idx, m[c_idx] * w_norm[:, None])
        return out

    def unit_rows(m: NDArray[np.float64]) -> NDArray[np.float64]:
        norms = np.linalg.norm(m, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return m / norms

    total = np.zeros((n, dimensions))
    current = projection
    for weight in HOP_WEIGHTS:
        current = propagate(current)
        if weight:
            total += weight * unit_rows(current)
    # Center, then unit length: removes the direction every node shares (hubs).
    total -= total.mean(axis=0, keepdims=True)
    return nodes, unit_rows(total).astype(np.float32)


def build_embeddings(
    adjacency: Mapping[str, Mapping[str, float]],
    colistening: Mapping[str, Mapping[str, int]],
    genres: Mapping[str, Iterable[tuple[str, float]]],
    version: str,
    *,
    dimensions: int = DIMENSIONS,
    seed: int = 7,
) -> Embeddings:
    """Artist embeddings for one catalog version (genre nodes are dropped from the result)."""
    nodes, matrix = fastrp(
        build_edges(adjacency, colistening, genres), dimensions=dimensions, seed=seed
    )
    keep = [i for i, node in enumerate(nodes) if not node.startswith(GENRE_PREFIX)]
    return Embeddings(
        ids=tuple(nodes[i] for i in keep),
        matrix=matrix[keep] if keep else np.zeros((0, dimensions), dtype=np.float32),
        version=version,
    )
