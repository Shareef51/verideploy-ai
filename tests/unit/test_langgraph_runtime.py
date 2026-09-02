from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest

from verideploy.graphs.memory_repository import InMemoryGraphRuntimeRepository
from verideploy.graphs.runtime import (
    DeterministicNodeWrapper,
    GraphDefinition,
    GraphRegistry,
    GraphRunStatus,
    LangGraphRuntime,
)


class FakeCheckpointer:
    def __init__(self) -> None:
        self.state: dict[str, dict] = {}


class ResumeFakeGraph:
    def __init__(self, checkpointer: FakeCheckpointer, counters: dict[str, int], *, fail_once: list[bool]) -> None:
        self.cp = checkpointer
        self.counters = counters
        self.fail_once = fail_once

    async def ainvoke(self, input, config=None, **kwargs):
        thread_id = config["configurable"]["thread_id"]
        state = self.cp.state.setdefault(thread_id, {"completed": [], "values": {}})
        if "node1" not in state["completed"]:
            self.counters["node1"] += 1
            state["values"]["node1"] = "done"
            state["completed"].append("node1")
            if self.fail_once[0]:
                self.fail_once[0] = False
                raise RuntimeError("simulated worker crash after checkpoint")
        if "node2" not in state["completed"]:
            self.counters["node2"] += 1
            state["values"]["node2"] = "done"
            state["completed"].append("node2")
        return {"completed_nodes": list(state["completed"]), "final_output": dict(state["values"])}

    async def aget_state(self, config):
        thread_id = config["configurable"]["thread_id"]
        state = self.cp.state[thread_id]
        return SimpleNamespace(values={"completed_nodes": list(state["completed"]), "final_output": dict(state["values"])})

    async def astream(self, input, config=None, **kwargs):
        yield {"node": {"status": "started"}}
        yield {"node": {"status": "completed"}}


class BlockingGraph:
    async def ainvoke(self, input, config=None, **kwargs):
        await asyncio.sleep(10)
        return {"done": True}

    async def aget_state(self, config):
        return SimpleNamespace(values={})

    async def astream(self, input, config=None, **kwargs):
        yield {"waiting": True}


def _runtime(factory):
    registry = GraphRegistry()
    registry.register(GraphDefinition(name="test", version="1", factory=factory))
    return LangGraphRuntime(registry=registry, repository=InMemoryGraphRuntimeRepository(), checkpointer=FakeCheckpointer())


def test_registry_rejects_duplicate_definition():
    registry = GraphRegistry()
    definition = GraphDefinition(name="g", version="1", factory=lambda cp: BlockingGraph())
    registry.register(definition)
    with pytest.raises(ValueError):
        registry.register(definition)


@pytest.mark.asyncio
async def test_restart_resume_reuses_checkpoint_without_replaying_completed_node():
    counters = {"node1": 0, "node2": 0}
    fail_once = [True]
    runtime = _runtime(lambda cp: ResumeFakeGraph(cp, counters, fail_once=fail_once))
    tenant = uuid4(); run_id = uuid4(); thread_id = str(uuid4())
    with pytest.raises(RuntimeError, match="simulated worker crash"):
        await runtime.execute(tenant_id=tenant, correlation_id="corr", graph_name="test", graph_version="1", input_state={}, run_id=run_id, thread_id=thread_id)
    assert runtime.repository.get_run(tenant_id=tenant, run_id=run_id).status == GraphRunStatus.FAILED

    record, result = await runtime.execute(tenant_id=tenant, correlation_id="corr", graph_name="test", graph_version="1", input_state={}, run_id=run_id, thread_id=thread_id)
    assert record.status == GraphRunStatus.COMPLETED
    assert counters == {"node1": 1, "node2": 1}
    assert result["completed_nodes"] == ["node1", "node2"]
    events = runtime.repository.list_events(tenant_id=tenant, run_id=run_id)
    assert [event.sequence_number for event in events] == list(range(1, len(events) + 1))
    assert events[-1].event_type == "graph.run.completed"


@pytest.mark.asyncio
async def test_completed_run_returns_checkpoint_snapshot_without_reinvocation():
    counters = {"node1": 0, "node2": 0}; fail_once = [False]
    runtime = _runtime(lambda cp: ResumeFakeGraph(cp, counters, fail_once=fail_once))
    tenant=uuid4(); run_id=uuid4(); thread_id=str(uuid4())
    await runtime.execute(tenant_id=tenant, correlation_id="c", graph_name="test", graph_version="1", input_state={}, run_id=run_id, thread_id=thread_id)
    _, result = await runtime.execute(tenant_id=tenant, correlation_id="c", graph_name="test", graph_version="1", input_state={}, run_id=run_id, thread_id=thread_id)
    assert counters == {"node1": 1, "node2": 1}
    assert result["final_output"]["node2"] == "done"


@pytest.mark.asyncio
async def test_timeout_marks_run_timed_out():
    runtime = _runtime(lambda cp: BlockingGraph())
    tenant=uuid4(); run_id=uuid4()
    with pytest.raises(TimeoutError):
        await runtime.execute(tenant_id=tenant, correlation_id="c", graph_name="test", graph_version="1", input_state={}, run_id=run_id, timeout_seconds=0.01)
    assert runtime.repository.get_run(tenant_id=tenant, run_id=run_id).status == GraphRunStatus.TIMED_OUT


@pytest.mark.asyncio
async def test_cancellation_interrupts_running_graph():
    runtime = _runtime(lambda cp: BlockingGraph())
    tenant=uuid4(); run_id=uuid4()
    task = asyncio.create_task(runtime.execute(tenant_id=tenant, correlation_id="c", graph_name="test", graph_version="1", input_state={}, run_id=run_id, timeout_seconds=2))
    await asyncio.sleep(0.01)
    runtime.cancel(run_id)
    with pytest.raises(asyncio.CancelledError):
        await task
    assert runtime.repository.get_run(tenant_id=tenant, run_id=run_id).status == GraphRunStatus.CANCELLED


@pytest.mark.asyncio
async def test_stream_emits_updates_for_existing_run():
    counters = {"node1": 0, "node2": 0}
    runtime = _runtime(lambda cp: ResumeFakeGraph(cp, counters, fail_once=[False]))
    tenant=uuid4(); run_id=uuid4()
    runtime.repository.create_run(tenant_id=tenant, run_id=run_id, thread_id=str(run_id), graph_name="test", graph_version="1", correlation_id="c")
    chunks = [chunk async for chunk in runtime.stream(tenant_id=tenant, run_id=run_id, graph_name="test", graph_version="1")]
    assert chunks == [{"node": {"status": "started"}}, {"node": {"status": "completed"}}]


@pytest.mark.asyncio
async def test_deterministic_node_wrapper_skips_completed_and_enforces_timeout():
    calls = {"count": 0}
    async def node(state):
        calls["count"] += 1
        return {"value": 1}
    wrapper = DeterministicNodeWrapper("n", node, timeout_seconds=1)
    out = await wrapper({"completed_nodes": []})
    assert out["completed_nodes"] == ["n"] and calls["count"] == 1
    assert await wrapper({"completed_nodes": ["n"]}) == {}
    assert calls["count"] == 1

    async def slow(state):
        await asyncio.sleep(1)
        return {}
    with pytest.raises(TimeoutError):
        await DeterministicNodeWrapper("slow", slow, timeout_seconds=0.01)({})
