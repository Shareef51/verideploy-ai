from __future__ import annotations

from typing import Any

from verideploy.graphs.runtime import DeterministicNodeWrapper, GraphDefinition, GraphExecutionState


def build_smoke_graph(checkpointer: Any) -> Any:
    try:
        from langgraph.graph import END, START, StateGraph
    except ImportError as exc:  # pragma: no cover - production dependency
        raise RuntimeError("langgraph is required to build the production graph") from exc

    async def prepare(state: GraphExecutionState) -> dict[str, Any]:
        outputs = dict(state.get("node_outputs", {}))
        outputs["prepare"] = {"prepared": True}
        return {"node_outputs": outputs}

    async def finalize(state: GraphExecutionState) -> dict[str, Any]:
        return {"status": "COMPLETED", "final_output": {"prepared": "prepare" in state.get("node_outputs", {})}}

    graph = StateGraph(GraphExecutionState)
    graph.add_node("prepare", DeterministicNodeWrapper("prepare", prepare, timeout_seconds=30))
    graph.add_node("finalize", DeterministicNodeWrapper("finalize", finalize, timeout_seconds=30))
    graph.add_edge(START, "prepare")
    graph.add_edge("prepare", "finalize")
    graph.add_edge("finalize", END)
    return graph.compile(checkpointer=checkpointer)


SMOKE_GRAPH = GraphDefinition(
    name="runtime_smoke",
    version="1.0.0",
    factory=build_smoke_graph,
    description="Production runtime/checkpoint smoke graph; contains no business-agent logic.",
)
