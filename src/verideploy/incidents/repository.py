from __future__ import annotations

from typing import Protocol
from uuid import UUID

from sqlalchemy import JSON, DateTime, String, Uuid, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from verideploy.incidents.schemas import IncidentDataset


class Base(DeclarativeBase):
    pass


class SyntheticIncidentRow(Base):
    __tablename__ = "synthetic_incidents"
    incident_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)
    family_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    split: Mapped[str] = mapped_column(String(16), nullable=False)
    failure_mode: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    primary_service_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)
    environment_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    started_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    incident_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)


class IncidentDatasetRepository(Protocol):
    async def upsert_dataset(self, dataset: IncidentDataset) -> int: ...


class SqlAlchemyIncidentDatasetRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._session_factory = session_factory

    async def upsert_dataset(self, dataset: IncidentDataset) -> int:
        tenant = dataset.incidents[0].tenant_id if dataset.incidents else None
        if tenant is None:
            return 0
        async with self._session_factory() as session:
            async with session.begin():
                if session.bind and session.bind.dialect.name == "postgresql":
                    await session.execute(text("SELECT set_config('app.tenant_id', :tenant, true)"), {"tenant": str(tenant)})
                for incident in dataset.incidents:
                    existing = await session.get(SyntheticIncidentRow, incident.incident_id)
                    values = dict(tenant_id=incident.tenant_id, family_id=incident.family_id, split=incident.split.value, failure_mode=incident.failure_mode.value, primary_service_id=incident.primary_service_id, environment_id=incident.environment_id, started_at=incident.started_at, incident_sha256=incident.incident_sha256, payload=incident.model_dump(mode="json"))
                    if existing is None:
                        session.add(SyntheticIncidentRow(incident_id=incident.incident_id, **values))
                    else:
                        for key, value in values.items():
                            setattr(existing, key, value)
        return len(dataset.incidents)
