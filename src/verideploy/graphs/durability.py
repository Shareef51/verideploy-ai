from __future__ import annotations

import asyncio
import hashlib
import json
import threading
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Any, Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from verideploy.graphs.runtime import GraphRunStatus, LangGraphRuntime, NodeCancelledError


class LeaseConflictError(RuntimeError): pass
class LeaseLostError(RuntimeError): pass
class StepConflictError(RuntimeError): pass


class StepStatus(StrEnum):
    PENDING="pending"; RUNNING="running"; COMPLETED="completed"; FAILED="failed"; CANCELLED="cancelled"; COMPENSATED="compensated"

class CompensationStatus(StrEnum):
    NONE="none"; REQUIRED="required"; RUNNING="running"; COMPLETED="completed"; FAILED="failed"


class WorkflowLease(BaseModel):
    model_config=ConfigDict(extra="forbid")
    lease_id: UUID = Field(default_factory=uuid4)
    tenant_id: UUID
    run_id: UUID
    owner_id: str
    lease_token: UUID = Field(default_factory=uuid4)
    version: int = Field(default=1, ge=1)
    acquired_at: datetime
    heartbeat_at: datetime
    expires_at: datetime
    cancelled_at: datetime | None = None

    @property
    def active(self) -> bool:
        now=datetime.now(timezone.utc)
        return self.cancelled_at is None and self.expires_at > now


class DurableStep(BaseModel):
    model_config=ConfigDict(extra="forbid")
    step_id: UUID = Field(default_factory=uuid4)
    tenant_id: UUID
    run_id: UUID
    step_key: str
    idempotency_key: str
    status: StepStatus
    attempt_number: int = Field(default=1, ge=1)
    timeout_seconds: float = Field(gt=0, le=3600)
    output: dict[str, Any] | None = None
    output_sha256: str | None = None
    error_code: str | None = None
    compensation_status: CompensationStatus = CompensationStatus.NONE
    started_at: datetime | None = None
    completed_at: datetime | None = None
    updated_at: datetime


class DurabilityEvent(BaseModel):
    model_config=ConfigDict(extra="forbid")
    event_id: UUID = Field(default_factory=uuid4)
    tenant_id: UUID
    run_id: UUID
    sequence: int = Field(ge=1)
    event_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class RecoveryCandidate(BaseModel):
    model_config=ConfigDict(extra="forbid")
    tenant_id: UUID
    run_id: UUID
    previous_owner_id: str
    lease_expired_at: datetime
    reason: str = "lease_expired"


class ReplayResult(BaseModel):
    model_config=ConfigDict(extra="forbid")
    tenant_id: UUID
    run_id: UUID
    replay_id: UUID = Field(default_factory=uuid4)
    from_sequence: int = Field(ge=0)
    event_count: int = Field(ge=0)
    state_event_types: list[str]
    replay_sha256: str


class DurabilityRepository(Protocol):
    def acquire_lease(self, *, tenant_id: UUID, run_id: UUID, owner_id: str, ttl_seconds: float, now: datetime | None = None) -> WorkflowLease: ...
    def heartbeat(self, *, tenant_id: UUID, run_id: UUID, owner_id: str, lease_token: UUID, expected_version: int, ttl_seconds: float, now: datetime | None = None) -> WorkflowLease: ...
    def release_lease(self, *, tenant_id: UUID, run_id: UUID, owner_id: str, lease_token: UUID) -> None: ...
    def get_lease(self, *, tenant_id: UUID, run_id: UUID) -> WorkflowLease | None: ...
    def cancel_run(self, *, tenant_id: UUID, run_id: UUID, actor_id: str, reason: str) -> WorkflowLease | None: ...
    def list_stuck(self, *, tenant_id: UUID, stale_before: datetime) -> list[RecoveryCandidate]: ...
    def get_step(self, *, tenant_id: UUID, run_id: UUID, idempotency_key: str) -> DurableStep | None: ...
    def begin_step(self, *, tenant_id: UUID, run_id: UUID, step_key: str, idempotency_key: str, timeout_seconds: float, now: datetime | None = None) -> DurableStep: ...
    def complete_step(self, *, tenant_id: UUID, run_id: UUID, idempotency_key: str, output: dict[str, Any]) -> DurableStep: ...
    def fail_step(self, *, tenant_id: UUID, run_id: UUID, idempotency_key: str, error_code: str, compensation_required: bool) -> DurableStep: ...
    def compensate_step(self, *, tenant_id: UUID, run_id: UUID, idempotency_key: str, success: bool) -> DurableStep: ...
    def events(self, *, tenant_id: UUID, run_id: UUID, after_sequence: int = 0) -> list[DurabilityEvent]: ...


def _sha(payload: Mapping[str, Any]) -> str:
    raw=json.dumps(payload, sort_keys=True, separators=(",",":"), default=str).encode()
    return hashlib.sha256(raw).hexdigest()


class InMemoryDurabilityRepository:
    def __init__(self) -> None:
        self._leases: dict[tuple[UUID,UUID],WorkflowLease]={}
        self._steps: dict[tuple[UUID,UUID,str],DurableStep]={}
        self._events: dict[tuple[UUID,UUID],list[DurabilityEvent]]={}
        self._lock=threading.RLock()

    def _event(self, tenant_id: UUID, run_id: UUID, event_type: str, payload: dict[str,Any] | None=None) -> None:
        key=(tenant_id,run_id); arr=self._events.setdefault(key,[])
        arr.append(DurabilityEvent(tenant_id=tenant_id,run_id=run_id,sequence=len(arr)+1,event_type=event_type,payload=payload or {}))

    def acquire_lease(self, *, tenant_id: UUID, run_id: UUID, owner_id: str, ttl_seconds: float, now: datetime | None=None) -> WorkflowLease:
        if ttl_seconds <= 0: raise ValueError("lease ttl must be positive")
        now=now or datetime.now(timezone.utc); key=(tenant_id,run_id)
        with self._lock:
            existing=self._leases.get(key)
            if existing and existing.cancelled_at is not None: raise LeaseConflictError("run is cancelled")
            if existing and existing.expires_at > now and existing.owner_id != owner_id: raise LeaseConflictError("run lease is owned by another worker")
            version=(existing.version+1) if existing else 1
            lease=WorkflowLease(tenant_id=tenant_id,run_id=run_id,owner_id=owner_id,version=version,acquired_at=now,heartbeat_at=now,expires_at=now+timedelta(seconds=ttl_seconds))
            self._leases[key]=lease
            self._event(tenant_id,run_id,"workflow.lease.acquired",{"owner_id":owner_id,"version":version,"recovery":existing is not None})
            return lease.model_copy(deep=True)

    def heartbeat(self, *, tenant_id: UUID, run_id: UUID, owner_id: str, lease_token: UUID, expected_version: int, ttl_seconds: float, now: datetime | None=None) -> WorkflowLease:
        now=now or datetime.now(timezone.utc); key=(tenant_id,run_id)
        with self._lock:
            cur=self._leases.get(key)
            if not cur or cur.owner_id!=owner_id or cur.lease_token!=lease_token or cur.version!=expected_version or cur.cancelled_at is not None: raise LeaseLostError("workflow lease lost")
            if cur.expires_at <= now: raise LeaseLostError("workflow lease expired")
            nxt=cur.model_copy(update={"version":cur.version+1,"heartbeat_at":now,"expires_at":now+timedelta(seconds=ttl_seconds)})
            self._leases[key]=nxt; self._event(tenant_id,run_id,"workflow.lease.heartbeat",{"owner_id":owner_id,"version":nxt.version})
            return nxt.model_copy(deep=True)

    def release_lease(self, *, tenant_id: UUID, run_id: UUID, owner_id: str, lease_token: UUID) -> None:
        with self._lock:
            cur=self._leases.get((tenant_id,run_id))
            if cur and cur.owner_id==owner_id and cur.lease_token==lease_token:
                self._leases.pop((tenant_id,run_id),None); self._event(tenant_id,run_id,"workflow.lease.released",{"owner_id":owner_id})

    def get_lease(self, *, tenant_id: UUID, run_id: UUID) -> WorkflowLease | None:
        with self._lock:
            v=self._leases.get((tenant_id,run_id)); return v.model_copy(deep=True) if v else None

    def cancel_run(self, *, tenant_id: UUID, run_id: UUID, actor_id: str, reason: str) -> WorkflowLease | None:
        now=datetime.now(timezone.utc)
        with self._lock:
            cur=self._leases.get((tenant_id,run_id))
            if cur: self._leases[(tenant_id,run_id)]=cur.model_copy(update={"cancelled_at":now,"version":cur.version+1})
            self._event(tenant_id,run_id,"workflow.run.cancelled",{"actor_id":actor_id,"reason":reason})
            return self.get_lease(tenant_id=tenant_id,run_id=run_id)

    def list_stuck(self, *, tenant_id: UUID, stale_before: datetime) -> list[RecoveryCandidate]:
        with self._lock:
            out=[]
            for (t,r),lease in self._leases.items():
                if t==tenant_id and lease.cancelled_at is None and lease.expires_at <= stale_before:
                    out.append(RecoveryCandidate(tenant_id=t,run_id=r,previous_owner_id=lease.owner_id,lease_expired_at=lease.expires_at))
            return sorted(out,key=lambda x:(x.lease_expired_at,str(x.run_id)))

    def get_step(self, *, tenant_id: UUID, run_id: UUID, idempotency_key: str) -> DurableStep | None:
        with self._lock:
            x=self._steps.get((tenant_id,run_id,idempotency_key)); return x.model_copy(deep=True) if x else None

    def begin_step(self, *, tenant_id: UUID, run_id: UUID, step_key: str, idempotency_key: str, timeout_seconds: float, now: datetime | None=None) -> DurableStep:
        now=now or datetime.now(timezone.utc); key=(tenant_id,run_id,idempotency_key)
        with self._lock:
            existing=self._steps.get(key)
            if existing and existing.status==StepStatus.COMPLETED: return existing.model_copy(deep=True)
            if existing and existing.status==StepStatus.RUNNING: raise StepConflictError("step already running")
            attempt=(existing.attempt_number+1) if existing else 1
            step=DurableStep(tenant_id=tenant_id,run_id=run_id,step_key=step_key,idempotency_key=idempotency_key,status=StepStatus.RUNNING,attempt_number=attempt,timeout_seconds=timeout_seconds,started_at=now,updated_at=now,compensation_status=existing.compensation_status if existing else CompensationStatus.NONE)
            self._steps[key]=step; self._event(tenant_id,run_id,"workflow.step.started",{"step_key":step_key,"idempotency_key":idempotency_key,"attempt":attempt})
            return step.model_copy(deep=True)

    def complete_step(self, *, tenant_id: UUID, run_id: UUID, idempotency_key: str, output: dict[str, Any]) -> DurableStep:
        now=datetime.now(timezone.utc); key=(tenant_id,run_id,idempotency_key)
        with self._lock:
            cur=self._steps[key]
            if cur.status==StepStatus.COMPLETED: return cur.model_copy(deep=True)
            if cur.status!=StepStatus.RUNNING: raise StepConflictError("step is not running")
            nxt=cur.model_copy(update={"status":StepStatus.COMPLETED,"output":dict(output),"output_sha256":_sha(output),"completed_at":now,"updated_at":now,"error_code":None})
            self._steps[key]=nxt; self._event(tenant_id,run_id,"workflow.step.completed",{"idempotency_key":idempotency_key,"output_sha256":nxt.output_sha256})
            return nxt.model_copy(deep=True)

    def fail_step(self, *, tenant_id: UUID, run_id: UUID, idempotency_key: str, error_code: str, compensation_required: bool) -> DurableStep:
        now=datetime.now(timezone.utc); key=(tenant_id,run_id,idempotency_key)
        with self._lock:
            cur=self._steps[key]
            nxt=cur.model_copy(update={"status":StepStatus.FAILED,"error_code":error_code,"updated_at":now,"compensation_status":CompensationStatus.REQUIRED if compensation_required else CompensationStatus.NONE})
            self._steps[key]=nxt; self._event(tenant_id,run_id,"workflow.step.failed",{"idempotency_key":idempotency_key,"error_code":error_code,"compensation_required":compensation_required})
            return nxt.model_copy(deep=True)

    def compensate_step(self, *, tenant_id: UUID, run_id: UUID, idempotency_key: str, success: bool) -> DurableStep:
        now=datetime.now(timezone.utc); key=(tenant_id,run_id,idempotency_key)
        with self._lock:
            cur=self._steps[key]
            if cur.compensation_status not in {CompensationStatus.REQUIRED,CompensationStatus.RUNNING}: raise StepConflictError("compensation not required")
            nxt=cur.model_copy(update={"status":StepStatus.COMPENSATED if success else cur.status,"compensation_status":CompensationStatus.COMPLETED if success else CompensationStatus.FAILED,"updated_at":now})
            self._steps[key]=nxt; self._event(tenant_id,run_id,"workflow.step.compensated" if success else "workflow.step.compensation_failed",{"idempotency_key":idempotency_key})
            return nxt.model_copy(deep=True)

    def events(self, *, tenant_id: UUID, run_id: UUID, after_sequence: int=0) -> list[DurabilityEvent]:
        with self._lock: return [e.model_copy(deep=True) for e in self._events.get((tenant_id,run_id),[]) if e.sequence>after_sequence]


class LongRunningWorkflowCoordinator:
    def __init__(self, *, runtime: LangGraphRuntime, repository: DurabilityRepository, owner_id: str, lease_ttl_seconds: float=30.0, heartbeat_seconds: float=10.0) -> None:
        if heartbeat_seconds <= 0 or lease_ttl_seconds <= heartbeat_seconds: raise ValueError("lease ttl must exceed heartbeat interval")
        self.runtime=runtime; self.repository=repository; self.owner_id=owner_id; self.lease_ttl_seconds=lease_ttl_seconds; self.heartbeat_seconds=heartbeat_seconds

    async def execute(self, **kwargs: Any) -> tuple[Any, Any]:
        tenant_id=kwargs["tenant_id"]; run_id=kwargs.get("run_id") or uuid4(); kwargs["run_id"]=run_id
        thread_id=kwargs.get("thread_id") or str(run_id); kwargs["thread_id"]=thread_id
        existing=self.runtime.repository.get_run(tenant_id=tenant_id,run_id=run_id)
        if existing is None:
            self.runtime.repository.create_run(tenant_id=tenant_id,run_id=run_id,thread_id=thread_id,graph_name=kwargs["graph_name"],graph_version=kwargs["graph_version"],correlation_id=kwargs["correlation_id"])
        lease=self.repository.acquire_lease(tenant_id=tenant_id,run_id=run_id,owner_id=self.owner_id,ttl_seconds=self.lease_ttl_seconds)
        stop=asyncio.Event(); lost: list[Exception]=[]
        async def heartbeater() -> None:
            nonlocal lease
            while not stop.is_set():
                try: await asyncio.wait_for(stop.wait(),timeout=self.heartbeat_seconds); return
                except TimeoutError: pass
                try: lease=self.repository.heartbeat(tenant_id=tenant_id,run_id=run_id,owner_id=self.owner_id,lease_token=lease.lease_token,expected_version=lease.version,ttl_seconds=self.lease_ttl_seconds)
                except Exception as exc: lost.append(exc); self.runtime.cancel(run_id); return
        hb=asyncio.create_task(heartbeater())
        try:
            result=await self.runtime.execute(**kwargs)
            if lost: raise LeaseLostError("workflow lease lost during execution") from lost[0]
            return result
        finally:
            stop.set(); hb.cancel(); await asyncio.gather(hb,return_exceptions=True)
            self.repository.release_lease(tenant_id=tenant_id,run_id=run_id,owner_id=self.owner_id,lease_token=lease.lease_token)

    async def run_step(self, *, tenant_id: UUID, run_id: UUID, step_key: str, idempotency_key: str, timeout_seconds: float, func: Callable[[], Mapping[str,Any] | Awaitable[Mapping[str,Any]]], compensation: Callable[[], Any | Awaitable[Any]] | None=None) -> DurableStep:
        existing=self.repository.get_step(tenant_id=tenant_id,run_id=run_id,idempotency_key=idempotency_key)
        if existing and existing.status==StepStatus.COMPLETED: return existing
        self.repository.begin_step(tenant_id=tenant_id,run_id=run_id,step_key=step_key,idempotency_key=idempotency_key,timeout_seconds=timeout_seconds)
        try:
            value=func(); output=await asyncio.wait_for(value,timeout=timeout_seconds) if isinstance(value,Awaitable) else value
            return self.repository.complete_step(tenant_id=tenant_id,run_id=run_id,idempotency_key=idempotency_key,output=dict(output))
        except Exception as exc:
            failed=self.repository.fail_step(tenant_id=tenant_id,run_id=run_id,idempotency_key=idempotency_key,error_code=type(exc).__name__,compensation_required=compensation is not None)
            if compensation is not None:
                try:
                    c=compensation();
                    if isinstance(c,Awaitable): await c
                    return self.repository.compensate_step(tenant_id=tenant_id,run_id=run_id,idempotency_key=idempotency_key,success=True)
                except Exception:
                    self.repository.compensate_step(tenant_id=tenant_id,run_id=run_id,idempotency_key=idempotency_key,success=False)
            raise

    def cancel(self, *, tenant_id: UUID, run_id: UUID, actor_id: str, reason: str) -> None:
        self.repository.cancel_run(tenant_id=tenant_id,run_id=run_id,actor_id=actor_id,reason=reason); self.runtime.cancel(run_id)

    def detect_stuck(self, *, tenant_id: UUID, now: datetime | None=None) -> list[RecoveryCandidate]:
        now=now or datetime.now(timezone.utc)
        candidates=self.repository.list_stuck(tenant_id=tenant_id,stale_before=now)
        allowed={GraphRunStatus.RUNNING,GraphRunStatus.FAILED,GraphRunStatus.TIMED_OUT}
        return [c for c in candidates if (r:=self.runtime.repository.get_run(tenant_id=tenant_id,run_id=c.run_id)) is not None and r.status in allowed]

    async def recover(self, *, tenant_id: UUID, run_id: UUID, timeout_seconds: float=300.0) -> tuple[Any,Any]:
        record=self.runtime.repository.get_run(tenant_id=tenant_id,run_id=run_id)
        if record is None: raise KeyError("graph run not found")
        if record.status in {GraphRunStatus.WAITING_FOR_APPROVAL,GraphRunStatus.CANCELLED,GraphRunStatus.COMPLETED}:
            raise LeaseConflictError(f"run status is not recoverable: {record.status.value}")
        return await self.execute(tenant_id=tenant_id,correlation_id=record.correlation_id,graph_name=record.graph_name,graph_version=record.graph_version,input_state={},run_id=run_id,thread_id=record.thread_id,timeout_seconds=timeout_seconds)

    async def run_step_with_retry(self, *, tenant_id: UUID, run_id: UUID, step_key: str, idempotency_key: str, timeout_seconds: float, func: Callable[[], Mapping[str,Any] | Awaitable[Mapping[str,Any]]], max_attempts: int=3, backoff_seconds: float=0.0, compensation: Callable[[], Any | Awaitable[Any]] | None=None) -> DurableStep:
        if max_attempts < 1: raise ValueError("max_attempts must be >= 1")
        existing=self.repository.get_step(tenant_id=tenant_id,run_id=run_id,idempotency_key=idempotency_key)
        if existing and existing.status==StepStatus.COMPLETED: return existing
        last: Exception | None=None
        for attempt in range(max_attempts):
            try:
                return await self.run_step(tenant_id=tenant_id,run_id=run_id,step_key=step_key,idempotency_key=idempotency_key,timeout_seconds=timeout_seconds,func=func,compensation=None)
            except Exception as exc:
                last=exc
                if attempt+1 < max_attempts and backoff_seconds>0:
                    await asyncio.sleep(backoff_seconds*(2**attempt))
        if compensation is not None:
            try:
                current=self.repository.get_step(tenant_id=tenant_id,run_id=run_id,idempotency_key=idempotency_key)
                if current is not None and current.compensation_status==CompensationStatus.NONE:
                    self.repository.fail_step(tenant_id=tenant_id,run_id=run_id,idempotency_key=idempotency_key,error_code=type(last).__name__ if last else "failed",compensation_required=True)
                c=compensation();
                if isinstance(c,Awaitable): await c
                self.repository.compensate_step(tenant_id=tenant_id,run_id=run_id,idempotency_key=idempotency_key,success=True)
            except Exception:
                try: self.repository.compensate_step(tenant_id=tenant_id,run_id=run_id,idempotency_key=idempotency_key,success=False)
                except Exception: pass
        assert last is not None
        raise last

    def operational_replay(self, *, tenant_id: UUID, run_id: UUID, from_sequence: int=0) -> ReplayResult:
        events=self.repository.events(tenant_id=tenant_id,run_id=run_id,after_sequence=from_sequence)
        payload=[{"sequence":e.sequence,"event_type":e.event_type,"payload":e.payload,"occurred_at":e.occurred_at.isoformat()} for e in events]
        digest=_sha({"tenant_id":str(tenant_id),"run_id":str(run_id),"events":payload})
        return ReplayResult(tenant_id=tenant_id,run_id=run_id,from_sequence=from_sequence,event_count=len(events),state_event_types=[e.event_type for e in events],replay_sha256=digest)
