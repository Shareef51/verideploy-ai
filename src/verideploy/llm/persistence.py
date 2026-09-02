from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from threading import RLock
from uuid import UUID

from sqlalchemy import DateTime, String, Text, UniqueConstraint, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from verideploy.llm.contracts import AIRequest, AIResult


class ResponsePersistence(ABC):
    @abstractmethod
    async def save(self, *, tenant_id: UUID, request: AIRequest, result: AIResult) -> None: ...

    @abstractmethod
    async def get(self, *, tenant_id: UUID, provider_response_id: str) -> AIResult | None: ...


class InMemoryResponsePersistence(ResponsePersistence):
    def __init__(self) -> None:
        self._items: dict[tuple[UUID, str], AIResult] = {}
        self._lock = asyncio.Lock()

    async def save(self, *, tenant_id: UUID, request: AIRequest, result: AIResult) -> None:
        if result.provider_response_id is None:
            return
        async with self._lock:
            self._items[(tenant_id, result.provider_response_id)] = result.model_copy(deep=True)

    async def get(self, *, tenant_id: UUID, provider_response_id: str) -> AIResult | None:
        async with self._lock:
            value = self._items.get((tenant_id, provider_response_id))
            return value.model_copy(deep=True) if value else None


class Base(DeclarativeBase):
    pass


class AIResponseRow(Base):
    __tablename__ = "ai_responses"
    __table_args__ = (UniqueConstraint("tenant_id", "provider_response_id", name="uq_ai_response_tenant_provider_p8"),)

    provider_response_id: Mapped[str] = mapped_column(String(256), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    request_id: Mapped[str] = mapped_column(String(36), index=True)
    correlation_id: Mapped[str] = mapped_column(String(128), index=True)
    operation: Mapped[str] = mapped_column(String(128), index=True)
    request_json: Mapped[str] = mapped_column(Text)
    result_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SqlAlchemyResponsePersistence(ResponsePersistence):
    """Responses API Adapter durable response snapshots pending central table migration."""

    def __init__(self, database_url: str, *, create_schema: bool = False) -> None:
        self._engine = create_engine(database_url, future=True)
        if create_schema:
            Base.metadata.create_all(self._engine)
        self._lock = RLock()

    async def save(self, *, tenant_id: UUID, request: AIRequest, result: AIResult) -> None:
        if result.provider_response_id is None:
            return
        await asyncio.to_thread(self._save_sync, tenant_id, request, result)

    def _save_sync(self, tenant_id: UUID, request: AIRequest, result: AIResult) -> None:
        with self._lock, Session(self._engine) as session:
            existing = session.scalar(
                select(AIResponseRow).where(
                    AIResponseRow.tenant_id == str(tenant_id),
                    AIResponseRow.provider_response_id == result.provider_response_id,
                )
            )
            if existing:
                existing.result_json = result.model_dump_json()
                session.commit()
                return
            session.add(
                AIResponseRow(
                    provider_response_id=result.provider_response_id or "",
                    tenant_id=str(tenant_id),
                    request_id=str(request.request_id),
                    correlation_id=request.correlation_id,
                    operation=request.operation,
                    request_json=request.model_dump_json(),
                    result_json=result.model_dump_json(),
                    created_at=datetime.now(UTC),
                )
            )
            session.commit()

    async def get(self, *, tenant_id: UUID, provider_response_id: str) -> AIResult | None:
        return await asyncio.to_thread(self._get_sync, tenant_id, provider_response_id)

    def _get_sync(self, tenant_id: UUID, provider_response_id: str) -> AIResult | None:
        with Session(self._engine) as session:
            row = session.scalar(
                select(AIResponseRow).where(
                    AIResponseRow.tenant_id == str(tenant_id),
                    AIResponseRow.provider_response_id == provider_response_id,
                )
            )
            return AIResult.model_validate_json(row.result_json) if row else None
