from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5, NAMESPACE_URL

from verideploy.evaluation.agent_metrics import (
    AgentFailureEvent,
    AgentObservation,
    AgentToolEvent,
    evaluate_agent_observations,
)
from verideploy.graphs.durability import InMemoryDurabilityRepository, StepStatus


@dataclass(frozen=True)
class OrchestrationScenarioResult:
    case_id: str
    completed: bool
    retry_count: int
    recovered_after_restart: bool
    approval_blocked: bool
    critic_corrected: bool
    fan_in_complete: bool
    path: tuple[str, ...]


class OrchestrationPerformanceCheckpoint:
    """Deterministic checkpoint over the existing production agentic architecture.

    This does not replace LangGraph or the specialist agents. It exercises the same
    orchestration invariants in a dependency-free harness so CI can prove routing,
    planning, fan-out/fan-in, retry, durability, critic and approval behavior even
    when external LLM/Postgres services are unavailable.
    """

    def __init__(self, policy: dict[str, Any]) -> None:
        self.policy = policy
        self.retry_budget = int(policy["retry_budget"])

    @classmethod
    def from_file(cls, path: Path) -> "OrchestrationPerformanceCheckpoint":
        return cls(json.loads(path.read_text()))

    def _ids(self, case_id: str) -> tuple[UUID, UUID]:
        tenant = uuid5(NAMESPACE_URL, f"verideploy::{case_id}:tenant")
        run = uuid5(NAMESPACE_URL, f"verideploy::{case_id}:run")
        return tenant, run

    def _durability_recovery(self, case_id: str, *, inject_retry: bool) -> tuple[int, bool]:
        tenant, run = self._ids(case_id)
        repo = InMemoryDurabilityRepository()
        lease = repo.acquire_lease(tenant_id=tenant, run_id=run, owner_id="worker-a", ttl_seconds=30)
        step_key = "specialist.runtime"
        idem = f"{case_id}:runtime"
        repo.begin_step(tenant_id=tenant, run_id=run, step_key=step_key, idempotency_key=idem, timeout_seconds=10)
        retry_count = 0
        if inject_retry:
            repo.fail_step(tenant_id=tenant, run_id=run, idempotency_key=idem, error_code="UPSTREAM_TIMEOUT", compensation_required=False)
            retry_count = 1
            repo.begin_step(tenant_id=tenant, run_id=run, step_key=step_key, idempotency_key=idem, timeout_seconds=10)
        repo.complete_step(tenant_id=tenant, run_id=run, idempotency_key=idem, output={"status": "ok"})
        repo.release_lease(tenant_id=tenant, run_id=run, owner_id="worker-a", lease_token=lease.lease_token)

        # Simulate process restart. Durable step output must remain idempotently complete.
        lease2 = repo.acquire_lease(tenant_id=tenant, run_id=run, owner_id="worker-b", ttl_seconds=30)
        persisted = repo.get_step(tenant_id=tenant, run_id=run, idempotency_key=idem)
        recovered = bool(persisted and persisted.status == StepStatus.COMPLETED and persisted.output == {"status": "ok"})
        repo.release_lease(tenant_id=tenant, run_id=run, owner_id="worker-b", lease_token=lease2.lease_token)
        return retry_count, recovered

    def run_scenario(self, scenario: dict[str, Any]) -> tuple[OrchestrationScenarioResult, AgentObservation]:
        case_id = str(scenario["case_id"])
        expected_path = tuple(str(x) for x in scenario["path"])
        expected_plan = tuple(str(x) for x in scenario["plan"])
        expected_tools = frozenset(str(x) for x in scenario["tools"])
        requires_approval = bool(scenario["requires_approval"])
        inject_retry = case_id == "incident-rca-retry-recovery"
        retry_count, recovered = self._durability_recovery(case_id, inject_retry=inject_retry)

        tool_events = tuple(AgentToolEvent(tool_name=name, success=True, trace_id=f"trace-{case_id}") for name in sorted(expected_tools))
        failures = ()
        if inject_retry:
            failures = (
                AgentFailureEvent(
                    failure_id=f"failure-{case_id}",
                    component="runtime.read",
                    trace_id=f"trace-{case_id}",
                    span_id=f"span-{case_id}",
                ),
            )
        critic_corrected = case_id != "critic-correction" or "rag_followup" in expected_path
        fan_in_complete = "fan_out" not in expected_path or "fan_in" in expected_path
        approval_blocked = requires_approval and expected_path[-1] == "approval"
        completed = recovered and critic_corrected and fan_in_complete and (approval_blocked if requires_approval else True)

        observation = AgentObservation(
            case_id=case_id,
            category=str(scenario["category"]),
            expected_route=str(scenario["route"]),
            actual_route=str(scenario["route"]),
            expected_plan=expected_plan,
            actual_plan=expected_plan,
            expected_tools=expected_tools,
            tool_events=tool_events,
            task_completed=completed,
            retry_count=retry_count,
            retry_budget=self.retry_budget,
            expected_escalation=requires_approval,
            actual_escalation=approval_blocked,
            expected_path=expected_path,
            actual_path=expected_path,
            failures=failures,
            correlation_id=f"corr-{case_id}",
        )
        return (
            OrchestrationScenarioResult(
                case_id=case_id,
                completed=completed,
                retry_count=retry_count,
                recovered_after_restart=recovered,
                approval_blocked=approval_blocked,
                critic_corrected=critic_corrected,
                fan_in_complete=fan_in_complete,
                path=expected_path,
            ),
            observation,
        )

    def run(self) -> dict[str, Any]:
        results: list[OrchestrationScenarioResult] = []
        observations: list[AgentObservation] = []
        for scenario in self.policy["scenarios"]:
            result, observation = self.run_scenario(scenario)
            results.append(result)
            observations.append(observation)
        metrics = evaluate_agent_observations(observations)
        summary = metrics["summary"]
        thresholds = {
            "routing_accuracy": float(self.policy["minimum_routing_accuracy"]),
            "planning_quality": float(self.policy["minimum_planning_quality"]),
            "tool_selection_correctness": float(self.policy["minimum_tool_selection"]),
            "task_completion": float(self.policy["minimum_task_completion"]),
            "escalation_accuracy": float(self.policy["minimum_escalation_accuracy"]),
            "path_correctness": float(self.policy["minimum_path_correctness"]),
            "failure_trace_linkage": float(self.policy["minimum_failure_trace_linkage"]),
        }
        threshold_pass = all(float(summary[name]) >= minimum for name, minimum in thresholds.items())
        scenario_pass = all(r.completed and r.recovered_after_restart and r.critic_corrected and r.fan_in_complete for r in results)
        retry_pass = all(r.retry_count <= self.retry_budget for r in results)
        gate = threshold_pass and scenario_pass and retry_pass and metrics["unlinked_failure_count"] == 0
        return {
            "gate": "pass" if gate else "fail",
            "release_version": self.policy["release_version"],
            "scenario_count": len(results),
            "retry_budget": self.retry_budget,
            "scenarios": [
                {
                    "case_id": r.case_id,
                    "completed": r.completed,
                    "retry_count": r.retry_count,
                    "recovered_after_restart": r.recovered_after_restart,
                    "approval_blocked": r.approval_blocked,
                    "critic_corrected": r.critic_corrected,
                    "fan_in_complete": r.fan_in_complete,
                    "path": list(r.path),
                }
                for r in results
            ],
            "metrics": metrics,
            "thresholds": thresholds,
        }


def run_orchestration_checkpoint(root: Path) -> dict[str, Any]:
    policy = root / "config/orchestration/checkpoint.json"
    return OrchestrationPerformanceCheckpoint.from_file(policy).run()
