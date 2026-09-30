"""Composition root: builds and wires every service exactly once per app."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Engine

from songnexus.agent.llm import MessagesClient
from songnexus.agent.service import AgentService
from songnexus.api.ratelimit import RateLimiter
from songnexus.core.config import Settings
from songnexus.readmodel import ReadModelStore
from songnexus.services.catalog_service import CatalogService
from songnexus.services.game_service import GameService
from songnexus.services.graph_service import GraphService


@dataclass
class Container:
    settings: Settings
    engine: Engine
    store: ReadModelStore
    graph: GraphService
    catalog: CatalogService
    agent: AgentService
    game: GameService
    agent_rate_limiter: RateLimiter


def build_container(settings: Settings, engine: Engine, llm_client: MessagesClient | None) -> Container:
    store = ReadModelStore(engine, settings.path_cache_size)
    graph = GraphService(store, settings)
    if settings.warm_analytics:
        store.on_reload(graph.warm)
    catalog = CatalogService(engine, store)
    return Container(
        settings=settings,
        engine=engine,
        store=store,
        graph=graph,
        catalog=catalog,
        agent=AgentService(graph, catalog, settings, llm_client),
        game=GameService(graph),
        agent_rate_limiter=RateLimiter(per_minute=settings.agent_rate_limit_per_minute),
    )
