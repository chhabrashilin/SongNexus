"""Agent API contract (POST /api/v1/agent/query)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from songnexus.schemas.api import EvidenceItem, PathOut

AgentMode = Literal["auto", "deterministic", "llm"]


class AgentQuery(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    mode: AgentMode = "auto"


class EntityRef(BaseModel):
    id: str
    name: str
    entity_type: str


class ToolCallTrace(BaseModel):
    step: int
    tool: str
    arguments: dict[str, Any]
    ok: bool
    summary: str
    latency_ms: float


class Grounding(BaseModel):
    """Result of checking the answer text against the evidence ledger."""

    checked: bool
    verified: bool
    unsupported_mentions: list[str] = Field(default_factory=list)
    path_verified: bool | None = None


class AgentResponse(BaseModel):
    question: str
    answer: str
    answer_source: Literal["template", "llm"]
    mode_used: Literal["deterministic", "llm"]
    intent: str | None
    entities: list[EntityRef]
    path: PathOut | None
    evidence: list[EvidenceItem]
    tools_used: list[ToolCallTrace]
    limitations: list[str]
    grounding: Grounding
    trace_id: str
    elapsed_ms: float
