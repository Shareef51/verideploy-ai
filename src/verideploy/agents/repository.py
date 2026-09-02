from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import JSON, DateTime, Integer, String, Uuid, create_engine, select, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from .contracts import AgentName, AgentRunStatus


class AgentRunRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: UUID
    tenant_id: UUID
    agent_name: AgentName
    prompt_name: str
    prompt_version: str
    prompt_sha256: str
    input_sha256: str
    status: AgentRunStatus
    output: dict[str, Any] | None = None
    max_tool_calls: int = 0
    tool_calls_used: int = 0
    error_code: str | None = None
    created_at: datetime
    updated_at: datetime


class AgentRunRepository(Protocol):
    def start(self, *, tenant_id: UUID, agent_name: AgentName, prompt_name: str, prompt_version: str, prompt_sha256: str, payload: dict[str, Any], max_tool_calls: int) -> AgentRunRecord: ...
    def complete(self, *, tenant_id: UUID, run_id: UUID, output: dict[str, Any], tool_calls_used: int) -> AgentRunRecord: ...
    def fail(self, *, tenant_id: UUID, run_id: UUID, error_code: str, tool_calls_used: int) -> AgentRunRecord: ...
    def get(self, *, tenant_id: UUID, run_id: UUID) -> AgentRunRecord | None: ...


def _hash_payload(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


class InMemoryAgentRunRepository:
    def __init__(self) -> None:
        self.records: dict[tuple[UUID, UUID], AgentRunRecord] = {}

    def start(self, *, tenant_id, agent_name, prompt_name, prompt_version, prompt_sha256, payload, max_tool_calls):
        now = datetime.now(timezone.utc); run_id = uuid4()
        record = AgentRunRecord(run_id=run_id, tenant_id=tenant_id, agent_name=agent_name, prompt_name=prompt_name, prompt_version=prompt_version, prompt_sha256=prompt_sha256, input_sha256=_hash_payload(payload), status=AgentRunStatus.RUNNING, max_tool_calls=max_tool_calls, created_at=now, updated_at=now)
        self.records[(tenant_id, run_id)] = record; return record

    def get(self, *, tenant_id, run_id): return self.records.get((tenant_id, run_id))

    def complete(self, *, tenant_id, run_id, output, tool_calls_used):
        record = self.records[(tenant_id, run_id)].model_copy(update={"status": AgentRunStatus.COMPLETED, "output": output, "tool_calls_used": tool_calls_used, "updated_at": datetime.now(timezone.utc)})
        self.records[(tenant_id, run_id)] = record; return record

    def fail(self, *, tenant_id, run_id, error_code, tool_calls_used):
        record = self.records[(tenant_id, run_id)].model_copy(update={"status": AgentRunStatus.FAILED, "error_code": error_code, "tool_calls_used": tool_calls_used, "updated_at": datetime.now(timezone.utc)})
        self.records[(tenant_id, run_id)] = record; return record


class Base(DeclarativeBase): pass
class AgentRunRow(Base):
    __tablename__ = "agent_runs"
    run_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)
    agent_name: Mapped[str] = mapped_column(String(40), nullable=False)
    prompt_name: Mapped[str] = mapped_column(String(80), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(32), nullable=False)
    prompt_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    input_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    output: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    max_tool_calls: Mapped[int] = mapped_column(Integer, nullable=False)
    tool_calls_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_code: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SqlAlchemyAgentRunRepository:
    def __init__(self, database_url: str, *, create_schema: bool = False) -> None:
        self.engine = create_engine(database_url, future=True)
        self.Session = sessionmaker(self.engine, expire_on_commit=False)
        if create_schema: Base.metadata.create_all(self.engine)

    def _tenant(self, session, tenant_id: UUID) -> None:
        if self.engine.dialect.name == "postgresql":
            session.execute(text("SELECT set_config('app.tenant_id', :tenant_id, true)"), {"tenant_id": str(tenant_id)})

    @staticmethod
    def _record(row: AgentRunRow) -> AgentRunRecord:
        return AgentRunRecord(run_id=row.run_id, tenant_id=row.tenant_id, agent_name=AgentName(row.agent_name), prompt_name=row.prompt_name, prompt_version=row.prompt_version, prompt_sha256=row.prompt_sha256, input_sha256=row.input_sha256, status=AgentRunStatus(row.status), output=row.output, max_tool_calls=row.max_tool_calls, tool_calls_used=row.tool_calls_used, error_code=row.error_code, created_at=row.created_at, updated_at=row.updated_at)

    def start(self, *, tenant_id, agent_name, prompt_name, prompt_version, prompt_sha256, payload, max_tool_calls):
        now=datetime.now(timezone.utc); row=AgentRunRow(run_id=uuid4(), tenant_id=tenant_id, agent_name=agent_name.value, prompt_name=prompt_name, prompt_version=prompt_version, prompt_sha256=prompt_sha256, input_sha256=_hash_payload(payload), status=AgentRunStatus.RUNNING.value, max_tool_calls=max_tool_calls, tool_calls_used=0, created_at=now, updated_at=now)
        with self.Session.begin() as s: self._tenant(s, tenant_id); s.add(row)
        return self._record(row)

    def get(self, *, tenant_id, run_id):
        with self.Session.begin() as s:
            self._tenant(s, tenant_id); row=s.scalar(select(AgentRunRow).where(AgentRunRow.tenant_id==tenant_id, AgentRunRow.run_id==run_id)); return self._record(row) if row else None

    def _finish(self, *, tenant_id, run_id, status, output, error_code, tool_calls_used):
        with self.Session.begin() as s:
            self._tenant(s, tenant_id); row=s.scalar(select(AgentRunRow).where(AgentRunRow.tenant_id==tenant_id, AgentRunRow.run_id==run_id))
            if row is None: raise KeyError("agent run not found")
            row.status=status.value; row.output=output; row.error_code=error_code; row.tool_calls_used=tool_calls_used; row.updated_at=datetime.now(timezone.utc)
        return self._record(row)

    def complete(self, *, tenant_id, run_id, output, tool_calls_used): return self._finish(tenant_id=tenant_id, run_id=run_id, status=AgentRunStatus.COMPLETED, output=output, error_code=None, tool_calls_used=tool_calls_used)
    def fail(self, *, tenant_id, run_id, error_code, tool_calls_used): return self._finish(tenant_id=tenant_id, run_id=run_id, status=AgentRunStatus.FAILED, output=None, error_code=error_code, tool_calls_used=tool_calls_used)
