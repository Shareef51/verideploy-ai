from __future__ import annotations

import asyncio
from itertools import permutations
from pathlib import Path
from uuid import uuid4

import pytest

from verideploy.graphs.memory_repository import InMemoryGraphRuntimeRepository
from verideploy.graphs.parallel import (
    DynamicParallelExecutor,
    ParallelPlan,
    ParallelTaskSpec,
    ParallelTaskStatus,
    RuntimeParallelEventSink,
    deterministic_fan_in,
    plan_to_langgraph_sends,
)
from verideploy.graphs.runtime import GraphRunStatus


class Planner:
    def __init__(self, tasks, *, concurrency=4, minimum_successes=1):
        self.plan_value = ParallelPlan.deterministic(
            planner_version="test-planner-v1",
            tasks=tasks,
            requested_concurrency=concurrency,
            minimum_successes=minimum_successes,
        )

    async def plan(self, state):
        return self.plan_value


def task(name: str, source: str, *, deadline: float | None = None) -> ParallelTaskSpec:
    return ParallelTaskSpec(
        task_id=name,
        source=source,
        node_name=f"{source}_node",
        payload={"name": name},
        deadline_seconds=deadline,
    )


def test_plan_is_deterministic_and_rejects_duplicate_task_ids():
    tasks = [task("b", "logs"), task("a", "metrics")]
    a = ParallelPlan.deterministic(planner_version="p1", tasks=tasks)
    b = ParallelPlan.deterministic(planner_version="p1", tasks=list(reversed(tasks)))
    assert a.plan_id == b.plan_id
    with pytest.raises(ValueError, match="task_id values must be unique"):
        ParallelPlan.deterministic(
            planner_version="p1", tasks=[task("dup", "logs"), task("dup", "metrics")]
        )


@pytest.mark.asyncio
async def test_planner_driven_fanout_executes_branches_and_fans_in_state():
    tasks = [task("metrics-1", "metrics"), task("logs-1", "logs"), task("traces-1", "traces")]

    async def worker(spec, state):
        await asyncio.sleep(0.005)
        return {
            "output": {"observed": spec.source},
            "state_update": {
                "agent_outputs": {spec.task_id: {"source": spec.source}},
                "evidence_ids": [f"ev-{spec.task_id}"],
                "completed_nodes": [spec.node_name],
            },
        }

    executor = DynamicParallelExecutor(
        planner=Planner(tasks),
        workers={source: worker for source in ("metrics", "logs", "traces")},
        max_concurrency=3,
    )
    result = await executor.execute({"investigation_id": "inv-1"})
    assert result.completed_count == 3
    assert result.failed_count == result.timed_out_count == 0
    assert result.partial_completion is False
    assert result.minimum_successes_met is True
    assert result.state_update["evidence_ids"] == ["ev-logs-1", "ev-metrics-1", "ev-traces-1"]
    assert set(result.state_update["agent_outputs"]) == {"metrics-1", "logs-1", "traces-1"}
    assert len(result.state_update_sha256) == 64


@pytest.mark.asyncio
async def test_bounded_concurrency_never_exceeds_limit():
    tasks = [task(f"t{i}", "source") for i in range(8)]
    active = 0
    peak = 0
    lock = asyncio.Lock()

    async def worker(spec, state):
        nonlocal active, peak
        async with lock:
            active += 1
            peak = max(peak, active)
        await asyncio.sleep(0.015)
        async with lock:
            active -= 1
        return {"output": {}, "state_update": {"node_outputs": {spec.task_id: {"ok": True}}}}

    executor = DynamicParallelExecutor(
        planner=Planner(tasks, concurrency=8),
        workers={"source": worker},
        max_concurrency=2,
    )
    result = await executor.execute({})
    assert result.completed_count == 8
    assert peak == 2


@pytest.mark.asyncio
async def test_per_source_deadline_yields_partial_completion_without_blocking_successes():
    tasks = [task("fast", "fast", deadline=0.1), task("slow", "slow", deadline=0.02)]

    async def fast_worker(spec, state):
        await asyncio.sleep(0.005)
        return {"output": {"ok": True}, "state_update": {"evidence_ids": ["ev-fast"]}}

    async def slow_worker(spec, state):
        await asyncio.sleep(0.2)
        return {"output": {"late": True}, "state_update": {"evidence_ids": ["ev-slow"]}}

    executor = DynamicParallelExecutor(
        planner=Planner(tasks, concurrency=2, minimum_successes=1),
        workers={"fast": fast_worker, "slow": slow_worker},
        max_concurrency=2,
    )
    result = await executor.execute({})
    by_id = {item.task_id: item for item in result.results}
    assert by_id["fast"].status == ParallelTaskStatus.COMPLETED
    assert by_id["slow"].status == ParallelTaskStatus.TIMED_OUT
    assert by_id["slow"].error_code == "SOURCE_DEADLINE_EXCEEDED"
    assert result.partial_completion is True
    assert result.minimum_successes_met is True
    assert result.state_update["evidence_ids"] == ["ev-fast"]
    assert any(error["task_id"] == "slow" for error in result.state_update["errors"])


@pytest.mark.asyncio
async def test_failed_branch_is_typed_partial_completion_and_does_not_discard_success():
    tasks = [task("good", "good"), task("bad", "bad")]

    async def good(spec, state):
        return {"output": {}, "state_update": {"citation_ids": ["cit-good"]}}

    async def bad(spec, state):
        raise RuntimeError("synthetic source failure")

    result = await DynamicParallelExecutor(
        planner=Planner(tasks, concurrency=2), workers={"good": good, "bad": bad}
    ).execute({})
    assert result.completed_count == 1 and result.failed_count == 1
    assert result.partial_completion is True
    assert result.state_update["citation_ids"] == ["cit-good"]
    failed = next(item for item in result.results if item.task_id == "bad")
    assert failed.error_code == "RuntimeError"


@pytest.mark.asyncio
async def test_deterministic_fan_in_ignores_branch_completion_order():
    tasks = [task("a", "a"), task("b", "b"), task("c", "c")]

    def workers(delays):
        result = {}
        for source in ("a", "b", "c"):
            async def worker(spec, state, source=source):
                await asyncio.sleep(delays[source])
                return {
                    "output": {"source": source},
                    "state_update": {
                        "agent_outputs": {source: {"ok": True}},
                        "evidence_ids": [f"ev-{source}"],
                    },
                }
            result[source] = worker
        return result

    first = await DynamicParallelExecutor(
        planner=Planner(tasks, concurrency=3), workers=workers({"a": .001, "b": .008, "c": .004})
    ).execute({})
    second = await DynamicParallelExecutor(
        planner=Planner(tasks, concurrency=3), workers=workers({"a": .008, "b": .001, "c": .005})
    ).execute({})
    assert first.state_update == second.state_update
    assert first.state_update_sha256 == second.state_update_sha256


def test_deterministic_fan_in_rejects_non_reducible_or_conflicting_branch_state():
    from datetime import datetime, timezone
    from verideploy.graphs.parallel import ParallelTaskResult
    now = datetime.now(timezone.utc)
    invalid = ParallelTaskResult(
        task_id="a", source="a", node_name="a", status=ParallelTaskStatus.COMPLETED,
        state_update={"status": "COMPLETED"}, duration_ms=1, started_at=now, completed_at=now,
    )
    with pytest.raises(ValueError, match="non-reducible state fields"):
        deterministic_fan_in([invalid])

    one = invalid.model_copy(update={"state_update": {"agent_outputs": {"shared": {"status": "ok"}}}})
    two = invalid.model_copy(update={"task_id": "b", "source": "b", "state_update": {"agent_outputs": {"shared": {"status": "failed"}}}})
    with pytest.raises(Exception, match="parallel state conflict"):
        deterministic_fan_in([one, two])


def test_langgraph_send_adapter_is_planner_ordered():
    pytest.importorskip("langgraph", reason="LangGraph package is not installed in this execution container")
    plan = ParallelPlan.deterministic(
        planner_version="p", tasks=[task("b", "z"), task("a", "a")]
    )
    sends = plan_to_langgraph_sends(plan, branch_node="worker")
    assert len(sends) == 2
    # LangGraph Send repr/attributes vary slightly by supported version; inspect input payload.
    payloads = [getattr(send, "arg", None) or getattr(send, "input", None) for send in sends]
    assert payloads[0]["parallel_task"]["task_id"] == "a"
    assert payloads[1]["parallel_task"]["task_id"] == "b"


@pytest.mark.asyncio
async def test_live_node_events_are_persisted_through_existing_runtime_event_store():
    repo = InMemoryGraphRuntimeRepository()
    tenant, run_id = uuid4(), uuid4()
    repo.create_run(
        tenant_id=tenant, run_id=run_id, thread_id=str(run_id),
        graph_name="investigation", graph_version="40", correlation_id="corr-40",
    )
    repo.set_status(tenant_id=tenant, run_id=run_id, status=GraphRunStatus.RUNNING)

    async def worker(spec, state):
        return {"output": {"ok": True}, "state_update": {"completed_nodes": [spec.node_name]}}

    result = await DynamicParallelExecutor(
        planner=Planner([task("a", "source")]),
        workers={"source": worker},
        event_sink=RuntimeParallelEventSink(repo, tenant, run_id),
    ).execute({})
    assert result.completed_count == 1
    events = repo.list_events(tenant_id=tenant, run_id=run_id)
    assert [event.event_type for event in events] == [
        "graph.parallel.plan.created",
        "graph.parallel.node.started",
        "graph.parallel.node.completed",
        "graph.parallel.fan_in.completed",
    ]
    assert events[-1].payload["state_update_sha256"] == result.state_update_sha256


@pytest.mark.asyncio
async def test_parallel_execution_reduces_wall_time_against_same_sequential_workload():
    tasks = [task(f"t{i}", "source") for i in range(4)]

    async def worker(spec, state):
        await asyncio.sleep(0.05)
        return {"output": {}, "state_update": {"node_outputs": {spec.task_id: {"ok": True}}}}

    parallel = await DynamicParallelExecutor(
        planner=Planner(tasks, concurrency=4), workers={"source": worker}, max_concurrency=4
    ).execute({})
    sequential = await DynamicParallelExecutor(
        planner=Planner(tasks, concurrency=1), workers={"source": worker}, max_concurrency=1
    ).execute({})
    assert parallel.state_update_sha256 == sequential.state_update_sha256
    assert parallel.wall_time_ms < sequential.wall_time_ms * 0.65


def test_config_and_version_are_wired():
    config = Path("src/verideploy/config.py").read_text()
    env = Path(".env.example").read_text()
    version = Path("src/verideploy/__init__.py").read_text()
    assert "langgraph_parallel_max_concurrency" in config
    assert "langgraph_parallel_max_tasks" in config
    assert "langgraph_parallel_default_deadline_seconds" in config
    factory = Path("src/verideploy/graphs/factory.py").read_text()
    assert "LANGGRAPH_PARALLEL_MAX_CONCURRENCY=8" in env
    assert "create_dynamic_parallel_executor" in factory
    assert "settings.langgraph_parallel_max_concurrency" in factory
    current=tuple(int(x) for x in version.split('\"')[1].split('.'))
    assert current >= (0,40,0)
