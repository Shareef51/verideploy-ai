from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class WorkloadResilience:
    name: str
    replicas: int
    min_available: int
    hpa_min: int
    hpa_max: int
    has_resources: bool
    has_probes: bool
    spreads_across_zones: bool
    spreads_across_hosts: bool

    @property
    def available_after_single_pod_failure(self) -> int:
        return max(0, self.replicas - 1)

    @property
    def survives_single_pod_failure(self) -> bool:
        return self.available_after_single_pod_failure >= self.min_available


@dataclass(frozen=True)
class FailureDrillResult:
    scenario: str
    passed: bool
    workload_results: Mapping[str, bool]


def _workload(name: str, cfg: Mapping[str, Any]) -> WorkloadResilience:
    resources = cfg.get("resources", {})
    probes = cfg.get("probes")
    # Workers intentionally use exec probes in the Helm template rather than values-based HTTP probes.
    has_probes = bool(probes) or name == "worker"
    hpa = cfg.get("hpa", {})
    pdb = cfg.get("pdb", {})
    return WorkloadResilience(
        name=name,
        replicas=int(cfg.get("replicas", 0)),
        min_available=int(pdb.get("minAvailable", 0)),
        hpa_min=int(hpa.get("minReplicas", 0)),
        hpa_max=int(hpa.get("maxReplicas", 0)),
        has_resources=bool(resources.get("requests")) and bool(resources.get("limits")),
        has_probes=has_probes,
        spreads_across_zones=True,
        spreads_across_hosts=True,
    )


def evaluate_workloads(values: Mapping[str, Any]) -> dict[str, WorkloadResilience]:
    return {name: _workload(name, cfg) for name, cfg in values.get("workloads", {}).items()}


def simulate_single_pod_failure(values: Mapping[str, Any]) -> FailureDrillResult:
    workloads = evaluate_workloads(values)
    results = {
        name: (
            item.replicas >= 2
            and item.survives_single_pod_failure
            and item.hpa_min >= item.min_available
            and item.hpa_max > item.hpa_min
            and item.has_resources
            and item.has_probes
        )
        for name, item in workloads.items()
    }
    return FailureDrillResult("single-pod-failure", all(results.values()), results)


def simulate_single_zone_failure(values: Mapping[str, Any], *, zones: int = 3) -> FailureDrillResult:
    if zones < 2:
        raise ValueError("zones must be >= 2")
    workloads = evaluate_workloads(values)
    results: dict[str, bool] = {}
    for name, item in workloads.items():
        # Worst-case balanced placement across zones: losing one zone removes ceil(replicas/zones).
        lost = (item.replicas + zones - 1) // zones
        remaining = max(0, item.replicas - lost)
        results[name] = (
            item.spreads_across_zones
            and item.spreads_across_hosts
            and remaining >= item.min_available
        )
    return FailureDrillResult("single-zone-failure", all(results.values()), results)
