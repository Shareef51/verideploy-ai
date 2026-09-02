from __future__ import annotations

import json
from itertools import permutations
from pathlib import Path

from verideploy.graphs.state import (
    CURRENT_STATE_SCHEMA_VERSION,
    StateEncryptionPolicy,
    append_unique,
    merge_maps,
    migrate_state,
    state_sha256,
)


def main() -> None:
    legacy = {
        "tenant_id": "11111111-1111-4111-8111-111111111111",
        "investigation_id": "active-investigation",
        "run_id": "22222222-2222-4222-8222-222222222222",
        "correlation_id": "correlation",
        "completed_nodes": ["intake"],
        "node_outputs": {"intake": {"incident_id": "INC-P39"}},
        "approval_ids": ["approval-1"],
    }
    migrated = migrate_state(legacy)
    if migrated.state["investigation_id"] != legacy["investigation_id"]:
        raise SystemExit("active investigation identity was not preserved")
    if migrated.state["run_id"] != legacy["run_id"]:
        raise SystemExit("active graph run identity was not preserved")
    if migrated.state["node_outputs"] != legacy["node_outputs"]:
        raise SystemExit("saved node output was not preserved")
    if migrated.state["approval_ids"] != legacy["approval_ids"]:
        raise SystemExit("human approval references were not preserved")

    branches = [
        {"rag": {"evidence": ["e1", "e2"]}},
        {"visual": {"evidence": ["v1"]}},
        {"runtime": {"evidence": ["r1"]}},
    ]
    merged_hashes: set[str] = set()
    for order in permutations(branches):
        merged = {}
        for branch in order:
            merged = merge_maps(merged, branch)
        merged_hashes.add(state_sha256({"state_schema_version": 3, "agent_outputs": merged}))
    if len(merged_hashes) != 1:
        raise SystemExit("parallel map reducer is order-dependent")

    append_results = {
        tuple(append_unique(order[:2], order[2:]))
        for order in permutations(["evidence-c", "evidence-a", "evidence-b"])
    }
    if len(append_results) != 1:
        raise SystemExit("parallel append reducer is order-dependent")

    StateEncryptionPolicy().validate({
        "state_schema_version": CURRENT_STATE_SCHEMA_VERSION,
        "credential_ref": "vault://verideploy/github",
    })

    report = {
        "valid": True,
        "current_state_schema_version": CURRENT_STATE_SCHEMA_VERSION,
        "migration_from": migrated.from_version,
        "migration_to": migrated.to_version,
        "migration_steps": list(migrated.applied_steps),
        "active_investigation_preserved": True,
        "run_identity_preserved": True,
        "approval_references_preserved": True,
        "parallel_map_permutations": 6,
        "parallel_map_unique_hashes": len(merged_hashes),
        "parallel_append_unique_results": len(append_results),
        "state_sha256": state_sha256(migrated.state),
        "encryption_policy": "reference_only",
    }
    target = Path("artifacts/state-validation.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
