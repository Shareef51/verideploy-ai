from __future__ import annotations
from functools import lru_cache
from uuid import UUID
from verideploy.config import get_settings
from verideploy.database.factory import create_database_manager
from verideploy.graphs.execution_projection import AgentExecutionProjection, project_agent_execution
from verideploy.graphs.repository import SqlAlchemyGraphRuntimeRepository

class GraphExecutionViewService:
    def __init__(self, repository): self.repository=repository
    def view(self, tenant_id: UUID, run_id: UUID) -> AgentExecutionProjection:
        run=self.repository.get_run(tenant_id=tenant_id,run_id=run_id)
        if run is None: raise KeyError("graph run not found")
        return project_agent_execution(run,self.repository.list_events(tenant_id=tenant_id,run_id=run_id,after_sequence=0))
    def events(self, tenant_id:UUID, run_id:UUID, after_sequence:int=0):
        if self.repository.get_run(tenant_id=tenant_id,run_id=run_id) is None: raise KeyError("graph run not found")
        return self.repository.list_events(tenant_id=tenant_id,run_id=run_id,after_sequence=after_sequence)

@lru_cache
def get_graph_execution_view_service()->GraphExecutionViewService:
    settings=get_settings()
    if not settings.database_url.startswith("postgresql"): raise RuntimeError("graph execution view requires PostgreSQL runtime database")
    db=create_database_manager(settings)
    return GraphExecutionViewService(SqlAlchemyGraphRuntimeRepository(db,statement_timeout_ms=settings.db_statement_timeout_ms))
