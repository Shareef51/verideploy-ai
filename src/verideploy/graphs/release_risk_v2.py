from __future__ import annotations

from typing import Any
from uuid import UUID

from verideploy.graphs.runtime import DeterministicNodeWrapper, GraphDefinition
from verideploy.graphs.state import GraphExecutionState
from verideploy.releases.risk_engine import calculate_release_risk
from verideploy.releases.schemas import ReleaseRiskPolicyInput


def build_release_risk_graph(checkpointer: Any) -> Any:
    """The durable release decision graph used by the Kafka worker."""
    try:
        from langgraph.graph import END, START, StateGraph
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("langgraph is required to build the release-risk graph") from exc

    async def assess(state: GraphExecutionState) -> dict[str, Any]:
        payload = state["input"]
        result = calculate_release_risk(
            assessment_id=UUID(payload["assessment_id"]),
            release_id=str(payload["release_id"]),
            policy=ReleaseRiskPolicyInput.model_validate(payload["policy"]),
            human_review_threshold=int(payload["human_review_threshold"]),
        )
        return {
            "node_outputs": {"risk_engine": result.model_dump(mode="json")},
            "evidence_ids": list(result.evidence_ids),
        }

    async def finalize(state: GraphExecutionState) -> dict[str, Any]:
        result = state["node_outputs"]["risk_engine"]
        return {"status": "COMPLETED", "final_output": dict(result)}

    graph = StateGraph(GraphExecutionState)
    graph.add_node("risk_engine", DeterministicNodeWrapper("risk_engine", assess, timeout_seconds=60))
    graph.add_node("release_decision", DeterministicNodeWrapper("release_decision", finalize, timeout_seconds=30))
    graph.add_edge(START, "risk_engine")
    graph.add_edge("risk_engine", "release_decision")
    graph.add_edge("release_decision", END)
    return graph.compile(checkpointer=checkpointer)


RELEASE_RISK_V2 = GraphDefinition(
    name="release_risk",
    version="2.0.0",
    factory=build_release_risk_graph,
    description="Durable release-risk calculation and decision workflow.",
)
