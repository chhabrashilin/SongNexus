"""Agent entry point: choose a mode, run it, verify, and assemble the response."""

from __future__ import annotations

import logging
import time
import uuid

from songnexus.agent.grounding import unsupported_mentions, verify_path
from songnexus.agent.ledger import EvidenceLedger
from songnexus.agent.llm import LlmOrchestrator, LlmUnavailableError, MessagesClient
from songnexus.agent.planner import DeterministicPlanner, classify
from songnexus.agent.tools import ToolContext
from songnexus.core.config import Settings
from songnexus.core.metrics import metrics
from songnexus.schemas.agent import AgentQuery, AgentResponse, Grounding
from songnexus.services.catalog_service import CatalogService
from songnexus.services.graph_service import GraphService

log = logging.getLogger(__name__)
MAX_EVIDENCE_IN_RESPONSE = 30


class AgentService:
    def __init__(
        self, graph: GraphService, catalog: CatalogService, settings: Settings, llm_client: MessagesClient | None
    ) -> None:
        self._graph = graph
        self._catalog = catalog
        self._settings = settings
        self._orchestrator = (
            LlmOrchestrator(llm_client, settings.agent_model, settings.agent_effort, settings.agent_max_steps)
            if llm_client is not None and settings.agent_llm_enabled
            else None
        )

    @property
    def llm_available(self) -> bool:
        return self._orchestrator is not None

    def query(self, request: AgentQuery) -> AgentResponse:
        started = time.perf_counter()
        trace_id = uuid.uuid4().hex[:16]
        question = request.question.strip()
        carried_limitations: list[str] = []

        use_llm = request.mode == "llm" or (request.mode == "auto" and self.llm_available)
        if use_llm and self._orchestrator is None:
            carried_limitations.append("The language model is not configured; answered with the deterministic planner.")
            use_llm = False

        ledger = EvidenceLedger()
        answer_source = "template"
        intent, _ = classify(question)
        if use_llm:
            assert self._orchestrator is not None
            try:
                result = self._orchestrator.run(self._context(ledger), question)
                answer, answer_source = result.answer, "llm"
            except LlmUnavailableError as exc:
                log.warning("llm unavailable; falling back", extra={"trace_id": trace_id, "reason": str(exc)})
                metrics.counter("agent.llm_fallback")
                carried_limitations.append(
                    f"The language model was unavailable ({exc}); answered with the deterministic planner."
                )
                use_llm = False
                ledger = EvidenceLedger()
        if not use_llm:
            plan = DeterministicPlanner(self._context(ledger)).run(question)
            answer, intent = plan.answer, plan.intent

        grounding = self._verify(ledger, answer, question)
        limitations = carried_limitations + ledger.limitations
        if grounding.unsupported_mentions:
            limitations.append(
                "The explanation mentions artists that no tool returned ("
                + ", ".join(grounding.unsupported_mentions)
                + "); treat those parts as unverified."
            )
        path = ledger.path
        if grounding.path_verified is False:
            limitations.append("The computed path failed re-verification against the graph and was withheld.")
            path = None

        elapsed = round((time.perf_counter() - started) * 1000, 1)
        mode_used = "llm" if use_llm else "deterministic"
        metrics.observe(f"agent.query.{mode_used}.ms", elapsed)
        metrics.counter(f"agent.query.{mode_used}")
        if grounding.unsupported_mentions:
            metrics.counter("agent.unsupported_mentions")
        log.info(
            "agent query",
            extra={
                "trace_id": trace_id,
                "mode": mode_used,
                "intent": intent,
                "tools": [f"{t.tool}:{'ok' if t.ok else 'err'}:{t.latency_ms}ms" for t in ledger.traces],
                "grounding_verified": grounding.verified,
                "elapsed_ms": elapsed,
            },
        )
        return AgentResponse(
            question=question,
            answer=answer,
            answer_source=answer_source,
            mode_used=mode_used,
            intent=intent,
            entities=list(ledger.entities.values()),
            path=path,
            evidence=list(ledger.evidence.values())[:MAX_EVIDENCE_IN_RESPONSE],
            tools_used=ledger.traces,
            limitations=limitations,
            grounding=grounding,
            trace_id=trace_id,
            elapsed_ms=elapsed,
        )

    def _context(self, ledger: EvidenceLedger) -> ToolContext:
        return ToolContext(graph=self._graph, catalog=self._catalog, ledger=ledger)

    def _verify(self, ledger: EvidenceLedger, answer: str, question: str) -> Grounding:
        model = self._graph.model
        path_ok = verify_path(model.graph, ledger.path, ledger.path_kinds) if ledger.path else None
        mentions = unsupported_mentions(answer, question, ledger.known_ids, ledger.known_names, model.search)
        return Grounding(
            checked=True,
            verified=not mentions and path_ok is not False,
            unsupported_mentions=mentions,
            path_verified=path_ok,
        )
