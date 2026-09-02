from __future__ import annotations

from dataclasses import dataclass

from verideploy.config import Settings
from verideploy.database.session import DatabaseManager
from verideploy.database.factory import create_database_manager
from verideploy.graphs.repository import SqlAlchemyGraphRuntimeRepository
from verideploy.graphs.saved_state import PostgresSavedStateRepository
from verideploy.graphs.runtime import (
    GraphRegistry,
    LangGraphRuntime,
    close_postgres_checkpointer,
    create_postgres_checkpointer,
)
from verideploy.graphs.incident_rca_v2 import IncidentAgentBundle, incident_rca_definition
from verideploy.graphs.release_risk_v2 import RELEASE_RISK_V2


@dataclass
class ProductionGraphRuntime:
    runtime: LangGraphRuntime
    database: DatabaseManager
    checkpointer: object

    async def close(self) -> None:
        await close_postgres_checkpointer(self.checkpointer)
        self.database.dispose()


async def create_production_graph_runtime(settings: Settings, *, incident_agents: IncidentAgentBundle) -> ProductionGraphRuntime:
    if not settings.database_url.startswith("postgresql"):
        raise RuntimeError("production LangGraph runtime requires PostgreSQL")
    checkpointer = await create_postgres_checkpointer(settings.database_url)
    database = create_database_manager(settings)
    repository = SqlAlchemyGraphRuntimeRepository(
        database,
        statement_timeout_ms=settings.db_statement_timeout_ms,
    )
    saved_state_repository = PostgresSavedStateRepository(
        database,
        statement_timeout_ms=settings.db_statement_timeout_ms,
    )
    registry = GraphRegistry()
    registry.register(incident_rca_definition(incident_agents))
    registry.register(RELEASE_RISK_V2)
    return ProductionGraphRuntime(
        runtime=LangGraphRuntime(registry=registry, repository=repository, checkpointer=checkpointer, durability=settings.langgraph_durability, saved_state_repository=saved_state_repository),
        database=database,
        checkpointer=checkpointer,
    )


def create_dynamic_parallel_executor(
    settings: Settings,
    *,
    planner: object,
    workers: dict[str, object],
    event_sink: object | None = None,
):
    """Build the dynamic-parallel executor from production configuration.

    The caller supplies the planner and source workers because those are investigation-
    specific capabilities; concurrency/deadline safety policy remains centralized in
    Settings so individual graphs cannot silently choose unbounded fan-out.
    """
    from verideploy.graphs.parallel import DynamicParallelExecutor

    return DynamicParallelExecutor(
        planner=planner,
        workers=workers,
        max_concurrency=settings.langgraph_parallel_max_concurrency,
        max_tasks=settings.langgraph_parallel_max_tasks,
        default_deadline_seconds=settings.langgraph_parallel_default_deadline_seconds,
        max_deadline_seconds=settings.langgraph_parallel_max_deadline_seconds,
        event_sink=event_sink,
    )


def create_long_running_workflow_coordinator(
    settings: Settings,
    *,
    runtime: LangGraphRuntime,
    database: DatabaseManager,
    owner_id: str,
):
    from verideploy.graphs.durability import LongRunningWorkflowCoordinator
    from verideploy.graphs.durability_repository import PostgresDurabilityRepository
    return LongRunningWorkflowCoordinator(
        runtime=runtime,
        repository=PostgresDurabilityRepository(database, statement_timeout_ms=settings.db_statement_timeout_ms),
        owner_id=owner_id,
        lease_ttl_seconds=settings.workflow_lease_ttl_seconds,
        heartbeat_seconds=settings.workflow_heartbeat_seconds,
    )
