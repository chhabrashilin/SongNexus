"""Deterministic planner: intent patterns -> fixed tool plans -> template answers.

This mode needs no LLM, is fully reproducible, and is the baseline the LLM
mode is evaluated against. It supports a small set of well-defined intents
and says so explicitly for anything else.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from songnexus.agent.tools import ToolContext, run_tool

_NAME = r"(.+?)"
_END = r"\s*[?.!]*\s*$"
_CONNECTED = r"(?:and|connected to|related to|linked to|connected with)"
_LIST = r"(?:who are |list |show (?:me )?)?(?:the )?"


def _intent(name: str, pattern: str) -> tuple[str, re.Pattern[str]]:
    return name, re.compile(pattern, re.I)


# Ordered: the first matching pattern wins.
INTENT_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    _intent(
        "connection", rf"^how (?:is|are|was|were) {_NAME} {_CONNECTED} {_NAME}(?: connected| related| linked)?{_END}"
    ),
    _intent(
        "connection",
        rf"^(?:what(?:'s| is) the )?(?:connection|path|link|degrees? of separation) "
        rf"(?:between|from) {_NAME} (?:and|to) {_NAME}{_END}",
    ),
    _intent("connection", rf"^(?:connect|link) {_NAME} (?:and|to|with) {_NAME}{_END}"),
    _intent("connection", rf"^(?:are|is) {_NAME} (?:and|connected to) {_NAME} connected{_END}"),
    _intent(
        "collaborators",
        rf"^who (?:has|have|did) {_NAME} (?:work(?:ed)?|collaborate(?:d)?|record(?:ed)?|perform(?:ed)?) with{_END}",
    ),
    _intent("collaborators", rf"^{_LIST}(?:collaborators|connections) (?:of|for) {_NAME}{_END}"),
    _intent("collaborators", rf"^who (?:worked|collaborated) with {_NAME}{_END}"),
    _intent("producers", rf"^who (?:produced|produces) (?:for |songs? (?:for|by) |tracks? (?:for|by) )?{_NAME}{_END}"),
    _intent("producers", rf"^{_LIST}producers (?:of|for) {_NAME}{_END}"),
    _intent(
        "genre_bridges",
        r"\b(?:artists?|musicians?|people) (?:who|that) (?:connect|bridge|link|span)s? "
        r"(.+?) (?:and|with|to) (.+?)(?:\s+and\b.*)?[?.!]*$",
    ),
    _intent(
        "bridges",
        r"\b(?:bridge|bridges|bridging|connects? (?:different|separate)|between (?:genres|scenes|communities))\b",
    ),
    _intent("central", r"\b(?:most (?:connected|central|influential|important)|hubs?|biggest network)\b"),
    _intent("about", rf"^(?:tell me about|who is|who are|what do you know about|describe) {_NAME}{_END}"),
]

SUPPORTED_QUESTIONS = (
    "How is <artist> connected to <artist>?  ·  Who has <artist> worked with?  ·  "
    "Who produced for <artist>?  ·  Which artists bridge different scenes?  ·  "
    "Who are the most connected artists?  ·  Tell me about <artist>."
)


@dataclass
class PlanResult:
    intent: str | None
    answer: str


def classify(question: str) -> tuple[str | None, tuple[str, ...]]:
    text = question.strip()
    for intent, pattern in INTENT_PATTERNS:
        match = pattern.search(text)
        if match:
            return intent, tuple(g.strip(" \"'“”") for g in match.groups() if g)
    return None, ()


class DeterministicPlanner:
    def __init__(self, ctx: ToolContext) -> None:
        self.ctx = ctx
        self.step = 0

    def _call(self, tool: str, **args: Any) -> tuple[bool, dict[str, Any]]:
        self.step += 1
        return run_tool(self.ctx, tool, args, self.step)

    def _resolve(self, name: str) -> tuple[str | None, str | None]:
        """Return (artist_id, problem). Never guesses between candidates."""
        ok, result = self._call("search_entities", query=name, entity_type="artist")
        if not ok:
            return None, f"Search for '{name}' failed."
        if result["decision"] == "matched":
            return result["resolved_id"], None
        candidates = [c["name"] for c in result["candidates"][:3]]
        if result["decision"] == "ambiguous" and candidates:
            options = ", ".join(candidates)
            return (
                None,
                f"'{name}' is ambiguous in the dataset (possible matches: {options}). Please use the full name.",
            )
        hint = f" Closest names: {', '.join(candidates)}." if candidates else ""
        return None, f"I couldn't confidently find an artist called '{name}' in the dataset.{hint}"

    def run(self, question: str) -> PlanResult:
        intent, names = classify(question)
        handlers: dict[str, Callable[[tuple[str, ...]], str]] = {
            "connection": self._connection,
            "collaborators": lambda n: self._neighbors(n, None, "has worked with"),
            "producers": lambda n: self._neighbors(n, ["production"], "has production connections with"),
            "bridges": lambda _: self._ranking("betweenness"),
            "genre_bridges": self._genre_bridges,
            "central": lambda _: self._ranking("pagerank"),
            "about": self._about,
        }
        if intent is None:
            self.ctx.ledger.add_limitation(
                "This question is outside what the deterministic planner supports; no tools were run."
            )
            return PlanResult(None, f"I can answer questions like: {SUPPORTED_QUESTIONS}")
        return PlanResult(intent, handlers[intent](names))

    # -- intents --------------------------------------------------------------

    def _connection(self, names: tuple[str, ...]) -> str:
        a_id, problem_a = self._resolve(names[0])
        b_id, problem_b = self._resolve(names[1])
        problems = [p for p in (problem_a, problem_b) if p]
        if problems or a_id is None or b_id is None:
            for p in problems:
                self.ctx.ledger.add_limitation(p)
            return " ".join(problems)
        if a_id == b_id:
            return "Both names refer to the same artist."
        ok, result = self._call(
            "find_path", source_id=a_id, target_id=b_id, mode="shortest", max_depth=6, alternatives=2
        )
        if not ok:
            return f"The path search failed: {result.get('error')}"
        if not result["found"]:
            return str(result["explanation"])
        # Provenance for the first hop grounds the answer in source records.
        path = self.ctx.ledger.path
        assert path is not None
        self._call("get_provenance", artist_a=path.hops[0].source, artist_b=path.hops[0].target, limit=5)
        steps = [
            f"{hop['from']} → {hop['to']}: {hop['evidence'][0]}"
            + (f" (+{hop['more_evidence']} more)" if hop["more_evidence"] else "")
            for hop in result["hops"]
        ]
        plural = "s" if result["steps"] != 1 else ""
        header = f"{result['path'][0]} and {result['path'][-1]} are {result['steps']} step{plural} apart."
        answer = "\n".join([header, *(f"{i}. {s}" for i, s in enumerate(steps, 1))])
        if result["alternatives"]:
            answer += "\nOther routes: " + "; ".join(" → ".join(alt) for alt in result["alternatives"])
        return answer

    def _neighbors(self, names: tuple[str, ...], categories: list[str] | None, verb: str) -> str:
        artist_id, problem = self._resolve(names[0])
        if artist_id is None:
            self.ctx.ledger.add_limitation(problem or "")
            return problem or ""
        args: dict[str, Any] = {"artist_id": artist_id, "limit": 8}
        if categories:
            args["categories"] = categories
        ok, result = self._call("get_neighbors", **args)
        if not ok:
            return f"Lookup failed: {result.get('error')}"
        if not result["neighbors"]:
            return f"{result['artist']} has no connections of that kind in the dataset."
        lines = [f"- {n['name']}: {n['evidence'][0]}" for n in result["neighbors"] if n["evidence"]]
        more = result["total_connected"] - len(result["neighbors"])
        tail = f"\n…and {more} more in the dataset." if more > 0 else ""
        return (
            f"{result['artist']} {verb} {result['total_connected']} artists in the dataset. Strongest connections:\n"
            + "\n".join(lines)
            + tail
        )

    def _ranking(self, metric: str) -> str:
        ok, result = self._call("rank_artists", metric=metric, scope="seed", limit=8)
        if not ok:
            return f"Ranking failed: {result.get('error')}"
        meaning = (
            "sit on the most shortest paths between other artists, "
            "i.e. they bridge otherwise separate parts of the network"
            if metric == "betweenness"
            else "are most central in the collaboration network (weighted PageRank)"
        )
        lines = [
            f"{r['rank']}. {r['name']}" + (f" ({', '.join(r['genres'])})" if r["genres"] else "")
            for r in result["ranking"]
        ]
        self.ctx.ledger.add_limitation(
            f"Rankings cover the artists whose discographies were loaded (the seed set); method: {result['algorithm']}."
        )
        return f"Among the fully loaded artists, these {meaning}:\n" + "\n".join(lines)

    def _genre_bridges(self, genres: tuple[str, ...]) -> str:
        self.ctx.ledger.add_limitation(
            f"Genre-filtered bridge discovery ({' / '.join(genres)}) is not implemented yet (roadmap Phase 3). "
            "Showing the overall bridge artists with their genres instead, so the genre overlap can be judged."
        )
        return self._ranking("betweenness")

    def _about(self, names: tuple[str, ...]) -> str:
        artist_id, problem = self._resolve(names[0])
        if artist_id is None:
            self.ctx.ledger.add_limitation(problem or "")
            return problem or ""
        ok, result = self._call("get_artist", artist_id=artist_id)
        if not ok:
            return f"Lookup failed: {result.get('error')}"
        parts = [f"{result['name']}"]
        if result["disambiguation"]:
            parts.append(f"({result['disambiguation']})")
        text = " ".join(parts) + "."
        if result["genres"]:
            text += f" Genres: {', '.join(result['genres'][:5])}."
        text += f" Connected to {result['connected_artists']} artists in the dataset"
        if result["connections_by_kind"]:
            text += " (" + ", ".join(f"{v} via {k}" for k, v in result["connections_by_kind"].items()) + ")"
        text += "."
        if result["albums_in_dataset"]:
            text += f" Albums loaded: {', '.join(result['albums_in_dataset'])}."
        if not result["fully_loaded"]:
            self.ctx.ledger.add_limitation(
                f"{result['name']} is known only through credits on other artists' releases; "
                "their own discography is not loaded."
            )
        return text
