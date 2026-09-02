from __future__ import annotations

import asyncio
import inspect
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Protocol
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, model_validator

from verideploy.graphs.runtime import RuntimeRepository
from verideploy.graphs.state import append_unique, merge_maps, state_sha256


PARALLEL_PLAN_NAMESPACE = UUID("3659566d-4cd3-5de6-882d-61a6c7f0572d")
PARALLEL_VERSION = "dynamic-parallel-v1"


class ParallelTaskStatus(StrEnum):
    COMPLETED = "COMPLETED"
    TIMED_OUT = "TIMED_OUT"
    FAILED = "FAILED"


class ParallelTaskSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    task_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")
    source: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_.:-]+$")
    node_name: str = Field(min_length=1, max_length=120)
    payload: dict[str, Any] = Field(default_factory=dict)
    deadline_seconds: float | None = Field(default=None, gt=0, le=600)


class ParallelPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    plan_id: UUID
    planner_version: str = Field(min_length=1, max_length=120)
    tasks: tuple[ParallelTaskSpec, ...]
    requested_concurrency: int = Field(default=4, ge=1, le=64)
    minimum_successes: int = Field(default=1, ge=0, le=64)

    @model_validator(mode="after")
    def validate_tasks(self) -> "ParallelPlan":
        task_ids = [task.task_id for task in self.tasks]
        if len(task_ids) != len(set(task_ids)):
            raise ValueError("parallel plan task_id values must be unique")
        if self.minimum_successes > len(self.tasks):
            raise ValueError("minimum_successes cannot exceed task count")
        return self

    @classmethod
    def deterministic(
        cls,
        *,
        planner_version: str,
        tasks: Sequence[ParallelTaskSpec],
        requested_concurrency: int = 4,
        minimum_successes: int = 1,
    ) -> "ParallelPlan":
        canonical = "|".join(
            f"{task.source}:{task.task_id}:{task.node_name}:{task.deadline_seconds}"
            for task in sorted(tasks, key=lambda item: (item.source, item.task_id))
        )
        plan_id = uuid5(PARALLEL_PLAN_NAMESPACE, f"{planner_version}|{canonical}")
        return cls(
            plan_id=plan_id,
            planner_version=planner_version,
            tasks=tuple(tasks),
            requested_concurrency=requested_concurrency,
            minimum_successes=minimum_successes,
        )


class ParallelTaskResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    task_id: str
    source: str
    node_name: str
    status: ParallelTaskStatus
    output: dict[str, Any] = Field(default_factory=dict)
    state_update: dict[str, Any] = Field(default_factory=dict)
    error_code: str | None = None
    duration_ms: float = Field(ge=0)
    started_at: datetime
    completed_at: datetime


class ParallelExecutionResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    plan_id: UUID
    parallel_version: str = PARALLEL_VERSION
    results: tuple[ParallelTaskResult, ...]
    state_update: dict[str, Any]
    state_update_sha256: str
    completed_count: int = Field(ge=0)
    timed_out_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)
    partial_completion: bool
    minimum_successes_met: bool
    wall_time_ms: float = Field(ge=0)


class ParallelPlanner(Protocol):
    def plan(self, state: Mapping[str, Any]) -> ParallelPlan | Awaitable[ParallelPlan]: ...


class ParallelWorker(Protocol):
    def __call__(
        self, task: ParallelTaskSpec, state: Mapping[str, Any]
    ) -> Mapping[str, Any] | Awaitable[Mapping[str, Any]]: ...


class ParallelEventSink(Protocol):
    def emit(self, *, event_type: str, node_name: str | None, payload: Mapping[str, Any]) -> None: ...


class NullParallelEventSink:
    def emit(self, *, event_type: str, node_name: str | None, payload: Mapping[str, Any]) -> None:
        return None


@dataclass(frozen=True)
class RuntimeParallelEventSink:
    repository: RuntimeRepository
    tenant_id: UUID
    run_id: UUID

    def emit(self, *, event_type: str, node_name: str | None, payload: Mapping[str, Any]) -> None:
        run = self.repository.get_run(tenant_id=self.tenant_id, run_id=self.run_id)
        if run is None:
            raise KeyError("graph run not found for parallel event")
        self.repository.append_event(
            tenant_id=self.tenant_id,
            run_id=self.run_id,
            thread_id=run.thread_id,
            graph_name=run.graph_name,
            graph_version=run.graph_version,
            event_type=event_type,
            node_name=node_name,
            payload=dict(payload),
        )


_ALLOWED_PARALLEL_STATE_FIELDS = frozenset(
    {
        "completed_nodes",
        "node_outputs",
        "agent_outputs",
        "evidence_ids",
        "citation_ids",
        "approval_ids",
        "errors",
        "runtime_events",
    }
)
_LIST_REDUCER_FIELDS = frozenset(
    {"completed_nodes", "evidence_ids", "citation_ids", "approval_ids", "errors", "runtime_events"}
)
_MAP_REDUCER_FIELDS = frozenset({"node_outputs", "agent_outputs"})


def _validate_parallel_state_update(update: Mapping[str, Any]) -> None:
    unexpected = set(update) - _ALLOWED_PARALLEL_STATE_FIELDS
    if unexpected:
        raise ValueError(
            "parallel branch attempted to write non-reducible state fields: "
            + ", ".join(sorted(unexpected))
        )
    for key in set(update) & _LIST_REDUCER_FIELDS:
        if not isinstance(update[key], (list, tuple)):
            raise TypeError(f"parallel state field {key} must be a sequence")
    for key in set(update) & _MAP_REDUCER_FIELDS:
        if not isinstance(update[key], Mapping):
            raise TypeError(f"parallel state field {key} must be a mapping")


def deterministic_fan_in(results: Sequence[ParallelTaskResult]) -> dict[str, Any]:
    """Reduce completed branch updates in canonical order.

    Runtime completion order is intentionally ignored. The state reducers provide
    deterministic de-duplication/deep merge and reject incompatible parallel writes.
    Failed/timed-out branches contribute explicit error records but never partial state.
    """
    state_update: dict[str, Any] = {}
    ordered = sorted(results, key=lambda item: (item.source, item.task_id))
    for result in ordered:
        if result.status == ParallelTaskStatus.COMPLETED:
            _validate_parallel_state_update(result.state_update)
            for field, value in result.state_update.items():
                if field in _LIST_REDUCER_FIELDS:
                    state_update[field] = append_unique(state_update.get(field, []), value)
                elif field in _MAP_REDUCER_FIELDS:
                    state_update[field] = merge_maps(state_update.get(field, {}), value)
        else:
            error = {
                "task_id": result.task_id,
                "source": result.source,
                "node_name": result.node_name,
                "status": result.status.value,
                "error_code": result.error_code,
            }
            state_update["errors"] = append_unique(state_update.get("errors", []), [error])

    # Persist a deterministic execution summary in state; per-branch wall-time telemetry
    # remains in runtime events and is intentionally excluded from the state hash.
    summary = {
        result.task_id: {
            "source": result.source,
            "node_name": result.node_name,
            "status": result.status.value,
            "error_code": result.error_code,
            "output": result.output if result.status == ParallelTaskStatus.COMPLETED else {},
        }
        for result in ordered
    }
    state_update["node_outputs"] = merge_maps(
        state_update.get("node_outputs", {}), {"parallel_fan_in": summary}
    )
    return state_update


def plan_to_langgraph_sends(plan: ParallelPlan, *, branch_node: str = "parallel_branch") -> list[Any]:
    """Translate a planner result to deterministic LangGraph Send objects.

    The executor below owns bounded concurrency/deadlines. This adapter exists for
    graphs that choose LangGraph's dynamic Send routing while retaining the same typed
    task contract and canonical ordering.
    """
    try:
        from langgraph.types import Send
    except ImportError as exc:  # pragma: no cover - production dependency
        raise RuntimeError("langgraph is required for dynamic Send fan-out") from exc
    return [
        Send(branch_node, {"parallel_task": task.model_dump(mode="json")})
        for task in sorted(plan.tasks, key=lambda item: (item.source, item.task_id))
    ]


class DynamicParallelExecutor:
    def __init__(
        self,
        *,
        planner: ParallelPlanner,
        workers: Mapping[str, ParallelWorker],
        max_concurrency: int = 8,
        max_tasks: int = 16,
        default_deadline_seconds: float = 30.0,
        max_deadline_seconds: float = 120.0,
        event_sink: ParallelEventSink | None = None,
    ) -> None:
        if not 1 <= max_concurrency <= 64:
            raise ValueError("max_concurrency must be between 1 and 64")
        if not 1 <= max_tasks <= 256:
            raise ValueError("max_tasks must be between 1 and 256")
        if default_deadline_seconds <= 0 or max_deadline_seconds <= 0:
            raise ValueError("parallel deadlines must be positive")
        if default_deadline_seconds > max_deadline_seconds:
            raise ValueError("default parallel deadline cannot exceed maximum deadline")
        self.planner = planner
        self.workers = dict(workers)
        self.max_concurrency = max_concurrency
        self.max_tasks = max_tasks
        self.default_deadline_seconds = default_deadline_seconds
        self.max_deadline_seconds = max_deadline_seconds
        self.event_sink = event_sink or NullParallelEventSink()

    async def _plan(self, state: Mapping[str, Any]) -> ParallelPlan:
        planned = self.planner.plan(state)
        if inspect.isawaitable(planned):
            planned = await planned
        if not isinstance(planned, ParallelPlan):
            raise TypeError("parallel planner must return ParallelPlan")
        if len(planned.tasks) > self.max_tasks:
            raise ValueError(
                f"parallel plan contains {len(planned.tasks)} tasks; maximum is {self.max_tasks}"
            )
        unknown = sorted({task.source for task in planned.tasks if task.source not in self.workers})
        if unknown:
            raise KeyError("no parallel worker registered for source(s): " + ", ".join(unknown))
        return planned

    async def execute(self, state: Mapping[str, Any]) -> ParallelExecutionResult:
        plan = await self._plan(state)
        concurrency = min(plan.requested_concurrency, self.max_concurrency)
        semaphore = asyncio.Semaphore(concurrency)
        self.event_sink.emit(
            event_type="graph.parallel.plan.created",
            node_name="parallel_planner",
            payload={
                "plan_id": str(plan.plan_id),
                "task_count": len(plan.tasks),
                "requested_concurrency": plan.requested_concurrency,
                "effective_concurrency": concurrency,
                "minimum_successes": plan.minimum_successes,
            },
        )
        wall_start = time.perf_counter()

        async def run_task(task: ParallelTaskSpec) -> ParallelTaskResult:
            async with semaphore:
                started_at = datetime.now(timezone.utc)
                started = time.perf_counter()
                deadline = min(
                    task.deadline_seconds or self.default_deadline_seconds,
                    self.max_deadline_seconds,
                )
                self.event_sink.emit(
                    event_type="graph.parallel.node.started",
                    node_name=task.node_name,
                    payload={
                        "plan_id": str(plan.plan_id),
                        "task_id": task.task_id,
                        "source": task.source,
                        "deadline_seconds": deadline,
                    },
                )
                worker = self.workers[task.source]
                try:
                    call = worker(task, state)
                    if inspect.isawaitable(call):
                        raw = await asyncio.wait_for(call, timeout=deadline)
                    else:
                        raw = call
                    if not isinstance(raw, Mapping):
                        raise TypeError("parallel worker must return a mapping")
                    raw_dict = dict(raw)
                    output = raw_dict.get("output", {})
                    state_update = raw_dict.get("state_update", {})
                    if not isinstance(output, Mapping) or not isinstance(state_update, Mapping):
                        raise TypeError("parallel worker output/state_update must be mappings")
                    _validate_parallel_state_update(state_update)
                    result = ParallelTaskResult(
                        task_id=task.task_id,
                        source=task.source,
                        node_name=task.node_name,
                        status=ParallelTaskStatus.COMPLETED,
                        output=dict(output),
                        state_update=dict(state_update),
                        duration_ms=(time.perf_counter() - started) * 1000,
                        started_at=started_at,
                        completed_at=datetime.now(timezone.utc),
                    )
                    self.event_sink.emit(
                        event_type="graph.parallel.node.completed",
                        node_name=task.node_name,
                        payload={
                            "plan_id": str(plan.plan_id),
                            "task_id": task.task_id,
                            "source": task.source,
                            "duration_ms": round(result.duration_ms, 3),
                        },
                    )
                    return result
                except TimeoutError:
                    result = ParallelTaskResult(
                        task_id=task.task_id,
                        source=task.source,
                        node_name=task.node_name,
                        status=ParallelTaskStatus.TIMED_OUT,
                        error_code="SOURCE_DEADLINE_EXCEEDED",
                        duration_ms=(time.perf_counter() - started) * 1000,
                        started_at=started_at,
                        completed_at=datetime.now(timezone.utc),
                    )
                    self.event_sink.emit(
                        event_type="graph.parallel.node.timed_out",
                        node_name=task.node_name,
                        payload={
                            "plan_id": str(plan.plan_id),
                            "task_id": task.task_id,
                            "source": task.source,
                            "deadline_seconds": deadline,
                        },
                    )
                    return result
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    result = ParallelTaskResult(
                        task_id=task.task_id,
                        source=task.source,
                        node_name=task.node_name,
                        status=ParallelTaskStatus.FAILED,
                        error_code=type(exc).__name__,
                        duration_ms=(time.perf_counter() - started) * 1000,
                        started_at=started_at,
                        completed_at=datetime.now(timezone.utc),
                    )
                    self.event_sink.emit(
                        event_type="graph.parallel.node.failed",
                        node_name=task.node_name,
                        payload={
                            "plan_id": str(plan.plan_id),
                            "task_id": task.task_id,
                            "source": task.source,
                            "error_code": result.error_code,
                        },
                    )
                    return result

        task_results = await asyncio.gather(
            *(run_task(task) for task in sorted(plan.tasks, key=lambda item: (item.source, item.task_id)))
        )
        ordered_results = tuple(sorted(task_results, key=lambda item: (item.source, item.task_id)))
        state_update = deterministic_fan_in(ordered_results)
        completed = sum(item.status == ParallelTaskStatus.COMPLETED for item in ordered_results)
        timed_out = sum(item.status == ParallelTaskStatus.TIMED_OUT for item in ordered_results)
        failed = sum(item.status == ParallelTaskStatus.FAILED for item in ordered_results)
        partial = completed != len(ordered_results)
        minimum_met = completed >= plan.minimum_successes
        wall_ms = (time.perf_counter() - wall_start) * 1000
        self.event_sink.emit(
            event_type="graph.parallel.fan_in.completed",
            node_name="parallel_fan_in",
            payload={
                "plan_id": str(plan.plan_id),
                "completed_count": completed,
                "timed_out_count": timed_out,
                "failed_count": failed,
                "partial_completion": partial,
                "minimum_successes_met": minimum_met,
                "state_update_sha256": state_sha256(state_update),
            },
        )
        return ParallelExecutionResult(
            plan_id=plan.plan_id,
            results=ordered_results,
            state_update=state_update,
            state_update_sha256=state_sha256(state_update),
            completed_count=completed,
            timed_out_count=timed_out,
            failed_count=failed,
            partial_completion=partial,
            minimum_successes_met=minimum_met,
            wall_time_ms=wall_ms,
        )
