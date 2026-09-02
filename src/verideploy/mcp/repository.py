from __future__ import annotations

from abc import ABC, abstractmethod
from threading import Lock

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from verideploy.database.session import DatabaseManager

from .contracts import MCPAuditRecord


class MCPAuditRepository(ABC):
    @abstractmethod
    def append(self, record: MCPAuditRecord) -> None: ...


class InMemoryMCPAuditRepository(MCPAuditRepository):
    def __init__(self) -> None:
        self.records: list[MCPAuditRecord] = []
        self._lock = Lock()

    def append(self, record: MCPAuditRecord) -> None:
        with self._lock:
            self.records.append(record)


class SqlAlchemyMCPAuditRepository(MCPAuditRepository):
    metadata = sa.MetaData()
    table = sa.Table(
        "mcp_tool_audit", metadata,
        sa.Column("audit_id", sa.Uuid(), primary_key=True),
        sa.Column("invocation_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.String(160), nullable=False),
        sa.Column("service_name", sa.String(120), nullable=False),
        sa.Column("tool_name", sa.String(160), nullable=False),
        sa.Column("server_name", sa.String(80), nullable=False),
        sa.Column("permission", sa.String(120), nullable=False),
        sa.Column("risk", sa.String(20), nullable=False),
        sa.Column("effect", sa.String(20), nullable=False),
        sa.Column("decision", sa.String(20), nullable=False),
        sa.Column("correlation_id", sa.String(128), nullable=False),
        sa.Column("arguments_sha256", sa.String(64), nullable=False),
        sa.Column("approval_id", sa.String(160), nullable=True),
        sa.Column("error_code", sa.String(120), nullable=True),
        sa.Column("duration_ms", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    def __init__(self, database_url: str, *, create_schema: bool = False, llmops_service=None) -> None:
        self.db = DatabaseManager(database_url)
        self.llmops_service = llmops_service
        if create_schema:
            self.metadata.create_all(self.db.engine)

    def append(self, record: MCPAuditRecord) -> None:
        payload = record.model_dump(mode="python")
        with self.db.transaction(record.tenant_id) as session:
            session.execute(sa.insert(self.table).values(**payload))
        if self.llmops_service is not None:
            from verideploy.llmops.schemas import LLMOpsEvent, LLMOpsKind
            self.llmops_service.record(LLMOpsEvent(tenant_id=record.tenant_id, correlation_id=record.correlation_id, tool_invocation_id=record.invocation_id, kind=LLMOpsKind.TOOL_CALL if record.error_code is None else LLMOpsKind.FAILURE, operation=f"mcp.{record.tool_name}", tool_name=record.tool_name, latency_ms=record.duration_ms, failure_code=record.error_code, payload={"arguments_sha256": record.arguments_sha256, "decision": record.decision.value, "server_name": record.server_name, "risk": record.risk.value}))
