"""SongNexus Daily: a once-a-day connection puzzle played on the real graph.

Rules: get from the start artist to the target artist by naming artists who are
*directly* connected, one step at a time. Every accepted step is backed by a
fact (shown to the player), so the game teaches true things about music.

Design choices:
* **Same puzzle for everyone, every day**, chosen deterministically from the
  date, so the puzzle needs no storage and results are comparable and shareable.
* **Fair puzzles:** start and target are both fully loaded artists whose
  shortest connection is 3 or 4 steps: never trivial, always solvable.
* **Warmer/colder feedback:** after each correct step the player learns how
  many steps remain (BFS distance), which turns a hard search into a readable
  game without revealing the route.
* **No spoilers from the server** except on explicit request (hints, solution).

Progress lives in the client. That is fine for a daily puzzle but not for
leaderboards, which would need server-side sessions (docs/vision.md).
"""

from __future__ import annotations

import hashlib
import random
from datetime import date

from songnexus.core.errors import GraphUnavailableError, InvalidRequestError, NotFoundError
from songnexus.graph import algorithms as alg
from songnexus.graph.projection import DEFAULT_CATEGORIES, kinds_for
from songnexus.readmodel import ReadModel
from songnexus.schemas import api
from songnexus.services.graph_service import GraphService

LAUNCH_DAY = date(2026, 9, 30)  # puzzle #1: the day the game was created
PAR_RANGE = (3, 4)
HINT_SIZE = 3


def _stable_int(text: str) -> int:
    return int(hashlib.sha256(text.encode()).hexdigest()[:16], 16)


class GameService:
    def __init__(self, graph: GraphService) -> None:
        self._graph = graph
        self._kinds = kinds_for(DEFAULT_CATEGORIES)

    def _candidate_pairs(self, model: ReadModel) -> list[tuple[str, str, int]]:
        """All (start, target, par) pairs of fully loaded artists at distance 3–4."""

        def compute() -> list[tuple[str, str, int]]:
            adj = model.graph.adjacency(self._kinds)
            seeds = sorted(n.id for n in model.graph.nodes.values() if n.hydrated)
            pairs = []
            for i, s in enumerate(seeds):
                dist = alg.bfs_distances(adj, s, max_depth=PAR_RANGE[1])
                for t in seeds[i + 1 :]:
                    d = dist.get(t)
                    if d is not None and PAR_RANGE[0] <= d <= PAR_RANGE[1]:
                        pairs.append((s, t, d))
            return pairs

        return model.analytics_cache.get_or_compute(("game_pairs", self._kinds), compute)

    def daily(self, day: date) -> api.DailyPuzzle:
        model = self._graph.model
        pairs = self._candidate_pairs(model)
        if not pairs:
            raise GraphUnavailableError("the loaded graph has no suitable puzzle pairs")
        pick = _stable_int(day.isoformat())
        s, t, par = pairs[pick % len(pairs)]
        if (pick >> 20) & 1:  # vary which end is the start
            s, t = t, s
        graph = model.graph
        return api.DailyPuzzle(
            number=(day - LAUNCH_DAY).days + 1,
            date=day.isoformat(),
            start=self._graph.path_node(graph, s),
            target=self._graph.path_node(graph, t),
            par=par,
            graph_version=model.version,
        )

    def _require(self, artist_id: str) -> None:
        if artist_id not in self._graph.model.graph.nodes:
            raise NotFoundError(f"artist {artist_id} not found")

    def check(self, request: api.GameCheckRequest) -> api.GameCheckResponse:
        for artist_id in (request.from_id, request.to_id, request.target_id):
            self._require(artist_id)
        if request.from_id == request.to_id:
            raise InvalidRequestError("pick a different artist than the current one")
        model = self._graph.model
        graph = model.graph
        adj = graph.adjacency(self._kinds)
        connected = request.to_id in adj[request.from_id]
        evidence: list[api.EvidenceItem] = []
        total = 0
        distance: int | None = None
        if connected:
            evidence, total = self._graph.evidence_items(graph, request.from_id, request.to_id, self._kinds, limit=2)
            result = alg.bidirectional_bfs_path(adj, request.to_id, request.target_id)
            distance = len(result.path) - 1 if result.path else None
        return api.GameCheckResponse(
            connected=connected,
            artist=self._graph.path_node(graph, request.to_id),
            evidence=evidence,
            evidence_total=total,
            distance_to_target=distance,
            reached_target=connected and request.to_id == request.target_id,
        )

    def hint(self, from_id: str, target_id: str) -> api.GameHint:
        """Three of the current artist's collaborators, at least one of them closer to the target."""
        self._require(from_id)
        self._require(target_id)
        model = self._graph.model
        graph = model.graph
        adj = graph.adjacency(self._kinds)
        to_target = alg.bfs_distances(adj, target_id)
        neighbors = sorted(adj[from_id])
        if not neighbors:
            return api.GameHint(candidates=[])
        best_distance = min(to_target.get(n, 10**6) for n in neighbors)
        closer = [n for n in neighbors if to_target.get(n) == best_distance]
        rng = random.Random(_stable_int(f"{from_id}|{target_id}"))  # same hint for everyone
        chosen = [rng.choice(closer)]
        others = [n for n in neighbors if n not in chosen]
        chosen += rng.sample(others, min(HINT_SIZE - 1, len(others)))
        rng.shuffle(chosen)
        return api.GameHint(candidates=[self._graph.path_node(graph, n) for n in chosen])

    def solution(self, day: date) -> api.PathResponse:
        puzzle = self.daily(day)
        return self._graph.path(
            puzzle.start.id, puzzle.target.id, "shortest", DEFAULT_CATEGORIES, max_depth=8, alternatives=2
        )
