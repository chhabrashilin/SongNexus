"""LLM orchestration with a scripted fake Messages client (no network, no cost)."""

from __future__ import annotations

import json
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import anthropic
import httpx2
import pytest
from sqlalchemy import Engine

from songnexus.agent.llm import FALLBACK_BETA
from songnexus.agent.service import AgentService
from songnexus.agent.tools import TOOLS
from songnexus.core.config import Settings
from songnexus.readmodel import ReadModelStore
from songnexus.schemas.agent import AgentQuery
from songnexus.services.catalog_service import CatalogService
from songnexus.services.graph_service import GraphService

Script = Callable[[dict[str, Any]], SimpleNamespace]


def text(value: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=value)


def tool_use(call_id: str, name: str, args: dict[str, Any]) -> SimpleNamespace:
    return SimpleNamespace(type="tool_use", id=call_id, name=name, input=args)


def message(*blocks: SimpleNamespace, stop_reason: str = "end_turn") -> SimpleNamespace:
    return SimpleNamespace(content=list(blocks), stop_reason=stop_reason, model="claude-opus-5-5")


def last_tool_results(kwargs: dict[str, Any]) -> dict[str, dict[str, Any]]:
    results = kwargs["messages"][-1]["content"]
    return {r["tool_use_id"]: json.loads(r["content"]) for r in results}


class FakeClient:
    def __init__(self, turns: list[Script]) -> None:
        self.turns = turns
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> SimpleNamespace:
        # Snapshot the message list: the orchestrator appends to it afterwards.
        self.calls.append({**kwargs, "messages": list(kwargs["messages"])})
        return self.turns[min(len(self.calls), len(self.turns)) - 1](kwargs)


def make_agent(engine: Engine, settings: Settings, client: FakeClient) -> AgentService:
    store = ReadModelStore(engine)
    return AgentService(GraphService(store, settings), CatalogService(engine, store), settings, client)


def connection_script(final_answer: str) -> list[Script]:
    return [
        lambda _: message(
            tool_use("s1", "search_entities", {"query": "Beta Singer"}),
            tool_use("s2", "search_entities", {"query": "Epsilon Drummer"}),
            stop_reason="tool_use",
        ),
        lambda kw: message(
            tool_use(
                "p1",
                "find_path",
                {
                    "source_id": last_tool_results(kw)["s1"]["resolved_id"],
                    "target_id": last_tool_results(kw)["s2"]["resolved_id"],
                },
            ),
            stop_reason="tool_use",
        ),
        lambda _: message(text(final_answer)),
    ]


def test_llm_answer_is_grounded_and_structured_fields_come_from_tools(
    loaded_engine: Engine, settings: Settings
) -> None:
    client = FakeClient(
        connection_script("Beta Singer reaches Epsilon Drummer through Delta Producer and Gamma Pianist.")
    )
    response = make_agent(loaded_engine, settings, client).query(
        AgentQuery(question="How is Beta Singer connected to Epsilon Drummer?")
    )

    assert response.mode_used == "llm" and response.answer_source == "llm"
    assert response.path is not None and response.path.nodes[0].name == "Beta Singer"
    assert response.grounding.verified and response.grounding.path_verified
    assert [t.tool for t in response.tools_used] == ["search_entities", "search_entities", "find_path"]
    assert response.evidence  # evidence comes from the ledger, not model text


def test_request_configuration(loaded_engine: Engine, settings: Settings) -> None:
    client = FakeClient(connection_script("Beta Singer and Epsilon Drummer are connected."))
    make_agent(loaded_engine, settings, client).query(
        AgentQuery(question="How is Beta Singer connected to Epsilon Drummer?")
    )
    first = client.calls[0]
    assert first["model"] == settings.agent_model
    assert first["betas"] == [FALLBACK_BETA] and first["fallbacks"] == "default"
    assert first["output_config"] == {"effort": settings.agent_effort}
    assert [t["name"] for t in first["tools"]] == list(TOOLS)
    assert "tool_choice" not in first
    # Parallel tool results go back in one user message, after the full assistant turn.
    second = client.calls[1]["messages"]
    assert second[-2]["role"] == "assistant" and second[-1]["role"] == "user"
    assert len(second[-1]["content"]) == 2


def test_invalid_and_unknown_tool_calls_are_rejected_and_reported(loaded_engine: Engine, settings: Settings) -> None:
    client = FakeClient(
        [
            lambda _: message(
                tool_use("a", "find_path", {"source_id": "not-a-uuid", "target_id": "x", "sql": "DROP TABLE artists"}),
                tool_use("b", "run_sql", {"query": "DELETE FROM artists"}),
                stop_reason="tool_use",
            ),
            lambda kw: (
                message(text("I could not run those tools."))
                if all("error" in r for r in last_tool_results(kw).values())
                else message(text("unexpected"))
            ),
        ]
    )
    response = make_agent(loaded_engine, settings, client).query(AgentQuery(question="anything", mode="llm"))
    assert response.answer == "I could not run those tools."
    assert [(t.tool, t.ok) for t in response.tools_used] == [("find_path", False), ("run_sql", False)]
    results = client.calls[1]["messages"][-1]["content"]
    assert all(r["is_error"] for r in results)
    assert "invalid arguments" in results[0]["content"] and "unknown tool" in results[1]["content"]


def test_unsupported_mentions_are_flagged(loaded_engine: Engine, settings: Settings) -> None:
    client = FakeClient(connection_script("Beta Singer connects to Epsilon Drummer, and Theta Loner is also involved."))
    response = make_agent(loaded_engine, settings, client).query(
        AgentQuery(question="How is Beta Singer connected to Epsilon Drummer?")
    )
    assert response.grounding.unsupported_mentions == ["Theta Loner"]
    assert not response.grounding.verified
    assert any("Theta Loner" in lim for lim in response.limitations)


def test_refusal_falls_back_to_deterministic_mode(loaded_engine: Engine, settings: Settings) -> None:
    client = FakeClient([lambda _: message(stop_reason="refusal")])
    response = make_agent(loaded_engine, settings, client).query(AgentQuery(question="Tell me about Alpha Rapper"))
    assert response.mode_used == "deterministic" and response.answer.startswith("Alpha Rapper")
    assert any("declined" in lim for lim in response.limitations)


def test_api_errors_fall_back_to_deterministic_mode(loaded_engine: Engine, settings: Settings) -> None:
    def fail(_: dict[str, Any]) -> SimpleNamespace:
        raise anthropic.APIConnectionError(request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages"))

    response = make_agent(loaded_engine, settings, FakeClient([fail])).query(
        AgentQuery(question="Tell me about Alpha Rapper")
    )
    assert response.mode_used == "deterministic"
    assert any("could not be reached" in lim for lim in response.limitations)


def test_step_budget_forces_a_final_answer(loaded_engine: Engine) -> None:
    settings = Settings(database_url="sqlite://", warm_analytics=False, agent_max_steps=2)

    def loop_or_answer(kwargs: dict[str, Any]) -> SimpleNamespace:
        if kwargs.get("tool_choice") == {"type": "none"}:
            return message(text("Here is what I found so far about Alpha Rapper."))
        return message(
            tool_use(f"t{len(kwargs['messages'])}", "search_entities", {"query": "Alpha Rapper"}),
            stop_reason="tool_use",
        )

    client = FakeClient([loop_or_answer])
    response = make_agent(loaded_engine, settings, client).query(AgentQuery(question="Tell me everything"))
    assert response.mode_used == "llm"
    assert len(client.calls) == 3 and client.calls[-1]["tool_choice"] == {"type": "none"}


@pytest.mark.parametrize("stop_reason", ["max_tokens"])
def test_truncated_responses_fall_back(loaded_engine: Engine, settings: Settings, stop_reason: str) -> None:
    client = FakeClient([lambda _: message(text("partial"), stop_reason=stop_reason)])
    response = make_agent(loaded_engine, settings, client).query(AgentQuery(question="Tell me about Alpha Rapper"))
    assert response.mode_used == "deterministic"
