from __future__ import annotations

from verideploy.observability.telemetry import traced_async

import asyncio
import inspect
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class GraphRunStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    TIMED_OUT = "TIMED_OUT"
    WAITING_FOR_APPROVAL = "WAITING_FOR_APPROVAL"


from verideploy.graphs.state import (
    CURRENT_STATE_SCHEMA_VERSION,
    GraphExecutionState,
    prepare_state_for_checkpoint,
)
from verideploy.graphs.saved_state import SavedStateRepository


class GraphRuntimeEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_id: UUID = Field(default_factory=uuid4)
    tenant_id: UUID
    run_id: UUID
    thread_id: str
    sequence_number: int = Field(ge=1)
    event_type: str
    graph_name: str
    graph_version: str
    node_name: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class GraphRunRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: UUID
    tenant_id: UUID
    thread_id: str
    graph_name: str
    graph_version: str
    correlation_id: str
    status: GraphRunStatus
    last_sequence: int = 0
    error_code: str | None = None
    created_at: datetime
    updated_at: datetime


class RuntimeRepository(Protocol):
    def create_run(self, *, tenant_id: UUID, run_id: UUID, thread_id: str, graph_name: str, graph_version: str, correlation_id: str) -> GraphRunRecord: ...
    def get_run(self, *, tenant_id: UUID, run_id: UUID) -> GraphRunRecord | None: ...
    def set_status(self, *, tenant_id: UUID, run_id: UUID, status: GraphRunStatus, error_code: str | None = None) -> GraphRunRecord: ...
    def append_event(self, *, tenant_id: UUID, run_id: UUID, thread_id: str, graph_name: str, graph_version: str, event_type: str, node_name: str | None = None, payload: dict[str, Any] | None = None) -> GraphRuntimeEvent: ...
    def list_events(self, *, tenant_id: UUID, run_id: UUID, after_sequence: int = 0) -> list[GraphRuntimeEvent]: ...


class CompiledGraphLike(Protocol):
    async def ainvoke(self, input: Any, config: Mapping[str, Any] | None = None, **kwargs: Any) -> Any: ...
    def astream(self, input: Any, config: Mapping[str, Any] | None = None, **kwargs: Any) -> AsyncIterator[Any]: ...
    async def aget_state(self, config: Mapping[str, Any]) -> Any: ...


GraphFactory = Callable[[Any], CompiledGraphLike]


@dataclass(frozen=True)
class GraphDefinition:
    name: str
    version: str
    factory: GraphFactory
    description: str = ""


class GraphRegistry:
    def __init__(self) -> None:
        self._graphs: dict[tuple[str, str], GraphDefinition] = {}

    def register(self, definition: GraphDefinition) -> None:
        key = (definition.name, definition.version)
        if key in self._graphs:
            raise ValueError(f"graph already registered: {definition.name}@{definition.version}")
        self._graphs[key] = definition

    def resolve(self, name: str, version: str) -> GraphDefinition:
        try:
            return self._graphs[(name, version)]
        except KeyError as exc:
            raise KeyError(f"unknown graph: {name}@{version}") from exc

    def list(self) -> tuple[GraphDefinition, ...]:
        return tuple(sorted(self._graphs.values(), key=lambda item: (item.name, item.version)))


class NodeCancelledError(asyncio.CancelledError):
    pass


class DeterministicNodeWrapper:
    """Adds bounded execution and replay-safe node completion markers.

    LangGraph checkpoints prevent completed super-steps from replaying on resume. The
    completed_nodes guard is a second idempotency boundary for nodes that may also be
    invoked in deterministic tests or custom recovery paths.
    """

    def __init__(
        self,
        name: str,
        func: Callable[[GraphExecutionState], Mapping[str, Any] | Awaitable[Mapping[str, Any]]],
        *,
        timeout_seconds: float,
        cancellation_check: Callable[[], bool] | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("node timeout must be positive")
        self.name = name
        self.func = func
        self.timeout_seconds = timeout_seconds
        self.cancellation_check = cancellation_check or (lambda: False)

    async def __call__(self, state: GraphExecutionState) -> dict[str, Any]:
        if self.name in state.get("completed_nodes", []):
            return {}
        if self.cancellation_check():
            raise NodeCancelledError(f"node cancelled before start: {self.name}")

        result = self.func(state)
        if inspect.isawaitable(result):
            output = await asyncio.wait_for(result, timeout=self.timeout_seconds)
        else:
            output = result
        if self.cancellation_check():
            raise NodeCancelledError(f"node cancelled after execution: {self.name}")
        return {**dict(output), "completed_nodes": [self.name]}


class LangGraphRuntime:
    def __init__(
        self,
        *,
        registry: GraphRegistry,
        repository: RuntimeRepository,
        checkpointer: Any,
        durability: str = "sync",
        saved_state_repository: SavedStateRepository | None = None,
    ) -> None:
        if durability != "sync":
            raise ValueError("production runtime requires sync checkpoint durability")
        self.registry = registry
        self.repository = repository
        self.checkpointer = checkpointer
        self.saved_state_repository = saved_state_repository
        self.durability = durability
        self._cancellations: dict[UUID, asyncio.Event] = {}

    @staticmethod
    def _config(thread_id: str) -> dict[str, Any]:
        return {"configurable": {"thread_id": thread_id}}

    async def _upgrade_saved_checkpoint(self, graph: Any, *, thread_id: str, tenant_id: UUID, run_id: UUID) -> tuple[dict[str, Any] | None, tuple[str, ...]]:
        try:
            snapshot = await graph.aget_state(self._config(thread_id))
        except (KeyError, LookupError):
            return None, ()
        raw = getattr(snapshot, "values", snapshot)
        if not isinstance(raw, Mapping) or not raw:
            return None, ()
        prepared = prepare_state_for_checkpoint(dict(raw))
        if prepared.applied_steps and hasattr(graph, "aupdate_state"):
            await graph.aupdate_state(self._config(thread_id), prepared.state)
            self.repository.append_event(
                tenant_id=tenant_id, run_id=run_id, thread_id=thread_id,
                graph_name=self.repository.get_run(tenant_id=tenant_id, run_id=run_id).graph_name,
                graph_version=self.repository.get_run(tenant_id=tenant_id, run_id=run_id).graph_version,
                event_type="graph.state.migrated",
                payload={
                    "from_version": prepared.from_version,
                    "to_version": prepared.to_version,
                    "steps": list(prepared.applied_steps),
                },
            )
            if self.saved_state_repository is not None:
                self.saved_state_repository.save_snapshot(
                    tenant_id=tenant_id, run_id=run_id, snapshot_kind="checkpoint_migrated",
                    state=prepared.state, migration_history=prepared.applied_steps,
                )
        return prepared.state, prepared.applied_steps

    def cancel(self, run_id: UUID) -> None:
        self._cancellations.setdefault(run_id, asyncio.Event()).set()

    @traced_async("langgraph.execute")
    async def execute(
        self,
        *,
        tenant_id: UUID,
        correlation_id: str,
        graph_name: str,
        graph_version: str,
        input_state: dict[str, Any],
        run_id: UUID | None = None,
        thread_id: str | None = None,
        timeout_seconds: float = 300.0,
        resume_value: dict[str, Any] | None = None,
    ) -> tuple[GraphRunRecord, Any]:
        definition = self.registry.resolve(graph_name, graph_version)
        run_id = run_id or uuid4()
        thread_id = thread_id or str(run_id)
        existing = self.repository.get_run(tenant_id=tenant_id, run_id=run_id)
        if existing is None:
            record = self.repository.create_run(
                tenant_id=tenant_id,
                run_id=run_id,
                thread_id=thread_id,
                graph_name=graph_name,
                graph_version=graph_version,
                correlation_id=correlation_id,
            )
        else:
            record = existing
            if record.thread_id != thread_id or record.graph_name != graph_name or record.graph_version != graph_version:
                raise ValueError("run identity does not match persisted graph metadata")
            if record.status == GraphRunStatus.COMPLETED:
                graph = definition.factory(self.checkpointer)
                upgraded, _ = await self._upgrade_saved_checkpoint(
                    graph, thread_id=thread_id, tenant_id=tenant_id, run_id=run_id
                )
                if upgraded is not None:
                    return record, upgraded
                snapshot = await graph.aget_state(self._config(thread_id))
                return record, getattr(snapshot, "values", snapshot)

        cancellation = self._cancellations.setdefault(run_id, asyncio.Event())
        self.repository.set_status(tenant_id=tenant_id, run_id=run_id, status=GraphRunStatus.RUNNING)
        self.repository.append_event(
            tenant_id=tenant_id, run_id=run_id, thread_id=thread_id,
            graph_name=graph_name, graph_version=graph_version, event_type="graph.run.started",
            payload={"resumed": existing is not None},
        )
        graph = definition.factory(self.checkpointer)
        if existing is not None:
            await self._upgrade_saved_checkpoint(
                graph, thread_id=thread_id, tenant_id=tenant_id, run_id=run_id
            )
        prepared = prepare_state_for_checkpoint({
            **input_state,
            "state_schema_version": input_state.get("state_schema_version", CURRENT_STATE_SCHEMA_VERSION),
            "tenant_id": str(tenant_id),
            "correlation_id": correlation_id,
            "graph_name": graph_name,
            "graph_version": graph_version,
            "run_id": str(run_id),
            "status": GraphRunStatus.RUNNING.value,
        })
        state: GraphExecutionState = prepared.state
        if self.saved_state_repository is not None:
            self.saved_state_repository.save_snapshot(
                tenant_id=tenant_id, run_id=run_id, snapshot_kind="input",
                state=state, migration_history=prepared.applied_steps,
            )
        try:
            if cancellation.is_set():
                raise NodeCancelledError("graph cancelled before execution")
            invoke_input: Any = state
            if resume_value is not None:
                from langgraph.types import Command
                invoke_input = Command(resume=resume_value)
            invoke_task = asyncio.create_task(graph.ainvoke(invoke_input, config=self._config(thread_id), durability=self.durability))
            cancellation_task = asyncio.create_task(cancellation.wait())
            done, _ = await asyncio.wait(
                {invoke_task, cancellation_task},
                timeout=timeout_seconds,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if not done:
                invoke_task.cancel()
                cancellation_task.cancel()
                await asyncio.gather(invoke_task, cancellation_task, return_exceptions=True)
                raise TimeoutError("graph execution timed out")
            if cancellation_task in done and cancellation.is_set():
                invoke_task.cancel()
                await asyncio.gather(invoke_task, return_exceptions=True)
                raise NodeCancelledError("graph cancelled")
            cancellation_task.cancel()
            await asyncio.gather(cancellation_task, return_exceptions=True)
            result = await invoke_task
            if isinstance(result, Mapping) and result.get("__interrupt__"):
                record = self.repository.set_status(tenant_id=tenant_id, run_id=run_id, status=GraphRunStatus.WAITING_FOR_APPROVAL)
                interrupts = result["__interrupt__"]
                payloads = [getattr(item, "value", item) for item in interrupts]
                self.repository.append_event(tenant_id=tenant_id,run_id=run_id,thread_id=thread_id,graph_name=graph_name,graph_version=graph_version,event_type="graph.approval.interrupted",payload={"interrupts":payloads})
                return record, result
            record = self.repository.set_status(tenant_id=tenant_id, run_id=run_id, status=GraphRunStatus.COMPLETED)
            from verideploy.evaluation.online_sampling import sampling_decision
            final_answer=result.get("final_answer",{}) if isinstance(result,Mapping) else {}
            sampling=sampling_decision(str(run_id),confidence=float(final_answer.get("confidence",1.0)))
            self.repository.append_event(tenant_id=tenant_id,run_id=run_id,thread_id=thread_id,graph_name=graph_name,graph_version=graph_version,event_type="evaluation.online.sampled",payload={**sampling.__dict__,"failed":False,"trace_checks":"scheduled"})
            self.repository.append_event(
                tenant_id=tenant_id, run_id=run_id, thread_id=thread_id,
                graph_name=graph_name, graph_version=graph_version, event_type="graph.run.completed",
            )
            if self.saved_state_repository is not None and isinstance(result, Mapping):
                final_state = prepare_state_for_checkpoint({**state, **dict(result)}).state
                self.saved_state_repository.save_snapshot(
                    tenant_id=tenant_id, run_id=run_id, snapshot_kind="result", state=final_state
                )
            return record, result
        except (NodeCancelledError, asyncio.CancelledError):
            record = self.repository.set_status(tenant_id=tenant_id, run_id=run_id, status=GraphRunStatus.CANCELLED, error_code="cancelled")
            self.repository.append_event(
                tenant_id=tenant_id, run_id=run_id, thread_id=thread_id,
                graph_name=graph_name, graph_version=graph_version, event_type="graph.run.cancelled",
            )
            raise
        except TimeoutError:
            record = self.repository.set_status(tenant_id=tenant_id, run_id=run_id, status=GraphRunStatus.TIMED_OUT, error_code="timeout")
            self.repository.append_event(
                tenant_id=tenant_id, run_id=run_id, thread_id=thread_id,
                graph_name=graph_name, graph_version=graph_version, event_type="graph.run.timed_out",
            )
            raise
        except Exception as exc:
            record = self.repository.set_status(tenant_id=tenant_id, run_id=run_id, status=GraphRunStatus.FAILED, error_code=type(exc).__name__)
            from verideploy.evaluation.online_sampling import sampling_decision
            sampling=sampling_decision(str(run_id),failed=True,confidence=0.0)
            self.repository.append_event(tenant_id=tenant_id,run_id=run_id,thread_id=thread_id,graph_name=graph_name,graph_version=graph_version,event_type="evaluation.online.sampled",payload={**sampling.__dict__,"failed":True,"annotation_dataset":"production-regressions"})
            self.repository.append_event(
                tenant_id=tenant_id, run_id=run_id, thread_id=thread_id,
                graph_name=graph_name, graph_version=graph_version, event_type="graph.run.failed",
                payload={"error_type": type(exc).__name__},
            )
            raise

    async def stream(
        self,
        *,
        tenant_id: UUID,
        run_id: UUID,
        graph_name: str,
        graph_version: str,
        input_state: dict[str, Any] | None = None,
        thread_id: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        definition = self.registry.resolve(graph_name, graph_version)
        record = self.repository.get_run(tenant_id=tenant_id, run_id=run_id)
        if record is None:
            raise KeyError("graph run not found")
        thread_id = thread_id or record.thread_id
        graph = definition.factory(self.checkpointer)
        source = None if input_state is None else input_state
        async for chunk in graph.astream(source, config=self._config(thread_id), stream_mode="updates", durability=self.durability):
            yield dict(chunk) if isinstance(chunk, Mapping) else {"value": chunk}


async def create_postgres_checkpointer(database_url: str) -> Any:
    """Create the official async PostgreSQL checkpointer.

    Import is intentionally deferred so unit tests stay deterministic without an
    installed LangGraph runtime. Production startup fails clearly if the required
    packages are missing.
    """
    try:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    except ImportError as exc:  # pragma: no cover - depends on provisioned runtime
        raise RuntimeError(
            "production runtime requires langgraph-checkpoint-postgres in the production environment"
        ) from exc

    dsn = database_url.replace("postgresql+psycopg://", "postgresql://", 1)
    manager = AsyncPostgresSaver.from_conn_string(dsn)
    checkpointer = await manager.__aenter__()
    await checkpointer.setup()
    setattr(checkpointer, "_verideploy_context_manager", manager)
    return checkpointer


async def close_postgres_checkpointer(checkpointer: Any) -> None:
    manager = getattr(checkpointer, "_verideploy_context_manager", None)
    if manager is not None:
        await manager.__aexit__(None, None, None)
