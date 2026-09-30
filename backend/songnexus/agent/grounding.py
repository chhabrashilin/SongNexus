"""Answer verification against the evidence ledger.

Two checks, both deterministic:

1. **Path verification** - every hop of the returned path is re-checked
   against the graph (edge exists with non-zero strength in the requested
   relationship kinds, no repeated artists). A tool bug cannot silently
   produce a fabricated connection.
2. **Mention check** - capitalized spans of the answer that exactly name an
   artist in the knowledge graph must be among the names the tools returned
   (or that the user typed). Quoted titles are skipped. Anything else is
   reported as an unsupported mention. This is a heuristic: it cannot detect
   claims about artists absent from the graph, and it is evaluated as such
   (docs/evaluation.md).
"""

from __future__ import annotations

import re
from itertools import pairwise

from songnexus.core.text import normalize
from songnexus.graph.projection import ArtistGraph
from songnexus.schemas.api import PathOut
from songnexus.search.index import SearchIndex

_TOKEN = re.compile(r"[\w$][\w$'’.&\-]*")
# Quoted spans are song/album titles copied from evidence, not artist mentions.
# Arrows, colons, semicolons, brackets and line breaks also end a name.
_BOUNDARY = re.compile(r"“[^”]*”|\"[^\"]*\"|[→:;()\[\]\n]|\.\s")
MAX_SPAN_TOKENS = 6
MIN_KEY_LENGTH = 3


def verify_path(graph: ArtistGraph, path: PathOut, kinds: frozenset[str]) -> bool:
    ids = [n.id for n in path.nodes]
    if len(set(ids)) != len(ids) or any(i not in graph.nodes for i in ids):
        return False
    for u, v in pairwise(ids):
        edge = graph.edge(u, v)
        if edge is None or edge.strength(kinds) <= 0:
            return False
    return len(path.hops) == len(ids) - 1


def unsupported_mentions(
    answer: str, question: str, known_ids: set[str], known_names: set[str], search: SearchIndex
) -> list[str]:
    allowed_names = {normalize(n) for n in known_names}
    question_norm = f" {normalize(question)} "
    found: list[str] = []
    for segment in _BOUNDARY.split(answer):
        tokens = [m.group(0).strip(".'’-") for m in _TOKEN.finditer(segment)]
        i = 0
        while i < len(tokens):
            matched = 0
            if tokens[i][:1].isupper() or tokens[i][:1].isdigit():
                for length in range(min(MAX_SPAN_TOKENS, len(tokens) - i), 0, -1):
                    span = " ".join(tokens[i : i + length])
                    key = normalize(span)
                    docs = search.exact(key, "artist") if len(key) >= MIN_KEY_LENGTH else []
                    if not docs:
                        continue
                    matched = length
                    supported = (
                        key in allowed_names
                        or any(d.entity_id in known_ids for d in docs)
                        or f" {key} " in question_norm
                    )
                    if not supported and span not in found:
                        found.append(span)
                    break
            i += matched or 1
    return found
