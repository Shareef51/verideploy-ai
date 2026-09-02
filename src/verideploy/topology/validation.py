from __future__ import annotations

import hashlib
import json
from collections import defaultdict

from verideploy.topology.schemas import TopologySnapshot, TopologyValidationReport


def _digest(snapshot: TopologySnapshot) -> str:
    payload = snapshot.model_dump(mode="json")
    payload["seed_sha256"] = ""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def validate_topology(snapshot: TopologySnapshot) -> TopologyValidationReport:
    errors: list[str] = []
    if snapshot.seed_sha256 != _digest(snapshot): errors.append("seed digest mismatch")
    collections = {
        "team": snapshot.teams, "owner": snapshot.owners, "environment": snapshot.environments,
        "service": snapshot.services, "dependency": snapshot.dependencies, "slo": snapshot.slos, "deployment": snapshot.deployments,
    }
    for label, rows in collections.items():
        ids = [getattr(row, f"{label}_id") for row in rows]
        if len(ids) != len(set(ids)): errors.append(f"duplicate {label} IDs")
    for label, rows in (("team", snapshot.teams), ("service", snapshot.services)):
        slugs = [row.slug for row in rows]
        if len(slugs) != len(set(slugs)): errors.append(f"duplicate {label} slugs")

    team_ids = {row.team_id for row in snapshot.teams}; service_ids = {row.service_id for row in snapshot.services}; env_ids = {row.environment_id for row in snapshot.environments}
    if any(owner.team_id not in team_ids for owner in snapshot.owners): errors.append("owner references unknown team")
    if any(service.team_id not in team_ids for service in snapshot.services): errors.append("service references unknown team")
    if any(dep.source_service_id not in service_ids or dep.target_service_id not in service_ids for dep in snapshot.dependencies): errors.append("dependency references unknown service")
    if any(dep.source_service_id == dep.target_service_id for dep in snapshot.dependencies): errors.append("self dependency is forbidden")
    if any(slo.service_id not in service_ids or slo.environment_id not in env_ids for slo in snapshot.slos): errors.append("SLO references unknown topology object")
    if any(dep.service_id not in service_ids or dep.environment_id not in env_ids for dep in snapshot.deployments): errors.append("deployment references unknown topology object")

    owners_by_team = defaultdict(int)
    for owner in snapshot.owners: owners_by_team[owner.team_id] += 1
    if any(owners_by_team[team.team_id] == 0 for team in snapshot.teams): errors.append("every team must have an owner")

    prod = next((env for env in snapshot.environments if env.name == "production"), None)
    if prod is None: errors.append("production environment is required")
    else:
        prod_slos = {slo.service_id for slo in snapshot.slos if slo.environment_id == prod.environment_id}
        prod_deployments = {dep.service_id for dep in snapshot.deployments if dep.environment_id == prod.environment_id}
        if prod_slos != service_ids: errors.append("every service must have a production SLO")
        if prod_deployments != service_ids: errors.append("every service must have a production deployment")

    # Ignore telemetry edges for application call-graph cycle validation.
    graph: dict[object, set[object]] = defaultdict(set)
    for dep in snapshot.dependencies:
        if dep.kind.value != "telemetry": graph[dep.source_service_id].add(dep.target_service_id)
    visiting: set[object] = set(); visited: set[object] = set()
    def visit(node: object) -> bool:
        if node in visiting: return False
        if node in visited: return True
        visiting.add(node)
        for child in graph[node]:
            if not visit(child): return False
        visiting.remove(node); visited.add(node); return True
    if any(not visit(node) for node in service_ids): errors.append("non-telemetry service dependency graph must be acyclic")

    return TopologyValidationReport(
        valid=not errors, seed_sha256=snapshot.seed_sha256, team_count=len(snapshot.teams), owner_count=len(snapshot.owners),
        service_count=len(snapshot.services), dependency_count=len(snapshot.dependencies), environment_count=len(snapshot.environments),
        slo_count=len(snapshot.slos), deployment_count=len(snapshot.deployments), errors=tuple(errors),
    )
