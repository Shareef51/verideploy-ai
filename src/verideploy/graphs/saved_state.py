from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Mapping, Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from verideploy.database.session import DatabaseManager
from verideploy.graphs.state import (
    STATE_ENCRYPTION_POLICY_VERSION,
    STATE_SERIALIZER_VERSION,
    canonical_state_json,
    prepare_state_for_checkpoint,
    state_sha256,
)


class SavedStateSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    snapshot_id: UUID = Field(default_factory=uuid4)
    tenant_id: UUID
    run_id: UUID
    investigation_id: str | None = None
    sequence: int = Field(ge=1)
    snapshot_kind: str
    state_schema_version: int = Field(ge=1)
    serializer_version: str = STATE_SERIALIZER_VERSION
    encryption_policy_version: str = STATE_ENCRYPTION_POLICY_VERSION
    state_sha256: str = Field(min_length=64, max_length=64)
    migration_history: tuple[str, ...] = ()
    state: dict[str, Any]
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class SavedStateRepository(Protocol):
    def save_snapshot(
        self,
        *,
        tenant_id: UUID,
        run_id: UUID,
        snapshot_kind: str,
        state: Mapping[str, Any],
        migration_history: tuple[str, ...] = (),
    ) -> SavedStateSnapshot: ...

    def latest_snapshot(self, *, tenant_id: UUID, run_id: UUID) -> SavedStateSnapshot | None: ...
    def list_snapshots(self, *, tenant_id: UUID, run_id: UUID) -> list[SavedStateSnapshot]: ...


def _build_snapshot(
    *,
    tenant_id: UUID,
    run_id: UUID,
    sequence: int,
    snapshot_kind: str,
    state: Mapping[str, Any],
    migration_history: tuple[str, ...],
) -> SavedStateSnapshot:
    prepared = prepare_state_for_checkpoint(state)
    canonical = json.loads(canonical_state_json(prepared.state))
    return SavedStateSnapshot(
        tenant_id=tenant_id,
        run_id=run_id,
        investigation_id=(str(canonical.get("investigation_id")) if canonical.get("investigation_id") else None),
        sequence=sequence,
        snapshot_kind=snapshot_kind,
        state_schema_version=int(canonical["state_schema_version"]),
        state_sha256=state_sha256(canonical),
        migration_history=tuple(migration_history) + prepared.applied_steps,
        state=canonical,
    )


class InMemorySavedStateRepository:
    def __init__(self) -> None:
        self._items: dict[tuple[UUID, UUID], list[SavedStateSnapshot]] = {}

    def save_snapshot(self, *, tenant_id: UUID, run_id: UUID, snapshot_kind: str, state: Mapping[str, Any], migration_history: tuple[str, ...] = ()) -> SavedStateSnapshot:
        key = (tenant_id, run_id)
        snapshot = _build_snapshot(
            tenant_id=tenant_id,
            run_id=run_id,
            sequence=len(self._items.get(key, ())) + 1,
            snapshot_kind=snapshot_kind,
            state=state,
            migration_history=migration_history,
        )
        self._items.setdefault(key, []).append(snapshot.model_copy(deep=True))
        return snapshot.model_copy(deep=True)

    def latest_snapshot(self, *, tenant_id: UUID, run_id: UUID) -> SavedStateSnapshot | None:
        items = self._items.get((tenant_id, run_id), ())
        return None if not items else items[-1].model_copy(deep=True)

    def list_snapshots(self, *, tenant_id: UUID, run_id: UUID) -> list[SavedStateSnapshot]:
        return [item.model_copy(deep=True) for item in self._items.get((tenant_id, run_id), ())]


class PostgresSavedStateRepository:
    def __init__(self, database: DatabaseManager, *, statement_timeout_ms: int = 15_000) -> None:
        self.database = database
        self.statement_timeout_ms = statement_timeout_ms

    def save_snapshot(self, *, tenant_id: UUID, run_id: UUID, snapshot_kind: str, state: Mapping[str, Any], migration_history: tuple[str, ...] = ()) -> SavedStateSnapshot:
        prepared = prepare_state_for_checkpoint(state)
        canonical = json.loads(canonical_state_json(prepared.state))
        history = tuple(migration_history) + prepared.applied_steps
        with self.database.tenant_session(tenant_id, statement_timeout_ms=self.statement_timeout_ms) as session:
            sequence = int(session.execute(text("""
                SELECT COALESCE(MAX(sequence), 0) + 1
                FROM graph_state_snapshots
                WHERE tenant_id=:tenant_id AND run_id=:run_id
            """), {"tenant_id": tenant_id, "run_id": run_id}).scalar_one())
            snapshot = SavedStateSnapshot(
                tenant_id=tenant_id,
                run_id=run_id,
                investigation_id=(str(canonical.get("investigation_id")) if canonical.get("investigation_id") else None),
                sequence=sequence,
                snapshot_kind=snapshot_kind,
                state_schema_version=int(canonical["state_schema_version"]),
                state_sha256=state_sha256(canonical),
                migration_history=history,
                state=canonical,
            )
            session.execute(text("""
                INSERT INTO graph_state_snapshots
                  (snapshot_id, tenant_id, run_id, investigation_id, sequence, snapshot_kind,
                   state_schema_version, serializer_version, encryption_policy_version,
                   state_sha256, migration_history, state_json, created_at)
                VALUES
                  (:snapshot_id, :tenant_id, :run_id, :investigation_id, :sequence, :snapshot_kind,
                   :state_schema_version, :serializer_version, :encryption_policy_version,
                   :state_sha256, CAST(:migration_history AS jsonb), CAST(:state_json AS jsonb), :created_at)
            """), {
                "snapshot_id": snapshot.snapshot_id,
                "tenant_id": tenant_id,
                "run_id": run_id,
                "investigation_id": snapshot.investigation_id,
                "sequence": sequence,
                "snapshot_kind": snapshot_kind,
                "state_schema_version": snapshot.state_schema_version,
                "serializer_version": snapshot.serializer_version,
                "encryption_policy_version": snapshot.encryption_policy_version,
                "state_sha256": snapshot.state_sha256,
                "migration_history": json.dumps(list(history), separators=(",", ":")),
                "state_json": canonical_state_json(canonical),
                "created_at": snapshot.created_at,
            })
            session.commit()
        return snapshot

    @staticmethod
    def _row(row: Mapping[str, Any]) -> SavedStateSnapshot:
        return SavedStateSnapshot(
            snapshot_id=row["snapshot_id"], tenant_id=row["tenant_id"], run_id=row["run_id"],
            investigation_id=row["investigation_id"], sequence=row["sequence"], snapshot_kind=row["snapshot_kind"],
            state_schema_version=row["state_schema_version"], serializer_version=row["serializer_version"],
            encryption_policy_version=row["encryption_policy_version"], state_sha256=row["state_sha256"],
            migration_history=tuple(row["migration_history"] or ()), state=deepcopy(dict(row["state_json"])),
            created_at=row["created_at"],
        )

    def latest_snapshot(self, *, tenant_id: UUID, run_id: UUID) -> SavedStateSnapshot | None:
        items = self._read(tenant_id=tenant_id, run_id=run_id, limit=1)
        return None if not items else items[0]

    def list_snapshots(self, *, tenant_id: UUID, run_id: UUID) -> list[SavedStateSnapshot]:
        return list(reversed(self._read(tenant_id=tenant_id, run_id=run_id, limit=None)))

    def _read(self, *, tenant_id: UUID, run_id: UUID, limit: int | None) -> list[SavedStateSnapshot]:
        limit_sql = "LIMIT 1" if limit == 1 else ""
        with self.database.tenant_session(tenant_id, statement_timeout_ms=self.statement_timeout_ms) as session:
            rows = session.execute(text(f"""
                SELECT snapshot_id, tenant_id, run_id, investigation_id, sequence, snapshot_kind,
                       state_schema_version, serializer_version, encryption_policy_version,
                       state_sha256, migration_history, state_json, created_at
                FROM graph_state_snapshots
                WHERE tenant_id=:tenant_id AND run_id=:run_id
                ORDER BY sequence DESC {limit_sql}
            """), {"tenant_id": tenant_id, "run_id": run_id}).mappings().all()
        return [self._row(row) for row in rows]
