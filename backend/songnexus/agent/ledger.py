"""The evidence ledger: everything the agent is allowed to state.

Tools write to the ledger; nothing else does. The response's structured
fields (entities, path, evidence) are read from the ledger, never parsed out
of model text. This is how "LLM-generated text != knowledge-graph fact" is
enforced structurally rather than by prompt alone.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from songnexus.schemas.agent import EntityRef, ToolCallTrace
from songnexus.schemas.api import EvidenceItem, PathOut


@dataclass
class EvidenceLedger:
    entities: dict[str, EntityRef] = field(default_factory=dict)
    evidence: dict[tuple[str, str, str], EvidenceItem] = field(default_factory=dict)
    path: PathOut | None = None
    path_kinds: frozenset[str] = frozenset()
    path_searched: bool = False
    limitations: list[str] = field(default_factory=list)
    traces: list[ToolCallTrace] = field(default_factory=list)
    # Every entity any tool returned (candidates, rankings, neighbors): what
    # the answer may mention without being flagged by the grounding check.
    known_ids: set[str] = field(default_factory=set)
    known_names: set[str] = field(default_factory=set)

    def add_known(self, entity_id: str, name: str) -> None:
        self.known_ids.add(entity_id)
        self.known_names.add(name)

    def add_entity(self, entity_id: str, name: str, entity_type: str = "artist") -> None:
        self.entities.setdefault(entity_id, EntityRef(id=entity_id, name=name, entity_type=entity_type))
        self.add_known(entity_id, name)

    def add_evidence(self, item: EvidenceItem) -> None:
        self.evidence.setdefault((item.kind, item.subject_id, item.sentence), item)

    def add_limitation(self, text: str) -> None:
        if text not in self.limitations:
            self.limitations.append(text)
