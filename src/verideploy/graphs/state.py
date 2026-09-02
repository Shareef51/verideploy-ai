from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Annotated, Any, TypedDict

CURRENT_STATE_SCHEMA_VERSION = 5
STATE_SERIALIZER_VERSION = "canonical-json-v1"
STATE_ENCRYPTION_POLICY_VERSION = "reference-only-v1"


class StateMigrationError(ValueError):
    """Raised when a persisted investigation state cannot be upgraded safely."""


class StateReducerConflict(ValueError):
    """Raised when parallel branches produce incompatible scalar state."""


def _canonical(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _canonical(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    if isinstance(value, set):
        return sorted((_canonical(item) for item in value), key=lambda item: json.dumps(item, sort_keys=True, default=str))
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("state datetime must be timezone-aware")
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return value


def canonical_state_json(state: Mapping[str, Any]) -> str:
    return json.dumps(_canonical(state), separators=(",", ":"), sort_keys=True, ensure_ascii=False)


def state_sha256(state: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_state_json(state).encode("utf-8")).hexdigest()


def append_unique(left: Sequence[Any] | None, right: Sequence[Any] | None) -> list[Any]:
    """Canonical ordered-set reducer independent of parallel branch completion order."""
    items: dict[str, Any] = {}
    for item in [*(left or ()), *(right or ())]:
        marker = json.dumps(_canonical(item), sort_keys=True, separators=(",", ":"), default=str)
        items.setdefault(marker, deepcopy(item))
    return [items[marker] for marker in sorted(items)]


def merge_maps(left: Mapping[str, Any] | None, right: Mapping[str, Any] | None) -> dict[str, Any]:
    """Deep deterministic merge used for independent parallel node/agent outputs.

    Identical writes are idempotent. Nested dictionaries are merged recursively. Two
    branches assigning different scalar values to the same path are rejected instead
    of relying on execution-order-dependent last-writer-wins behavior.
    """
    result = deepcopy(dict(left or {}))
    for key in sorted((right or {}).keys(), key=str):
        incoming = deepcopy((right or {})[key])
        if key not in result:
            result[key] = incoming
            continue
        existing = result[key]
        if isinstance(existing, Mapping) and isinstance(incoming, Mapping):
            result[key] = merge_maps(existing, incoming)
        elif existing == incoming:
            continue
        else:
            raise StateReducerConflict(f"parallel state conflict at key: {key}")
    return result


def strict_identity(left: Any, right: Any) -> Any:
    """Reducer for identity/scalar fields that must never disagree across branches."""
    # LangGraph initializes annotated numeric channels with their zero value.
    if left in (None, "", 0):
        return deepcopy(right)
    if right in (None, "", 0):
        return deepcopy(left)
    if left != right:
        raise StateReducerConflict(f"parallel scalar conflict: {left!r} != {right!r}")
    return deepcopy(left)


class GraphExecutionState(TypedDict, total=False):
    state_schema_version: Annotated[int, strict_identity]
    tenant_id: Annotated[str, strict_identity]
    user_id: Annotated[str, strict_identity]
    correlation_id: Annotated[str, strict_identity]
    investigation_id: Annotated[str, strict_identity]
    graph_name: Annotated[str, strict_identity]
    graph_version: Annotated[str, strict_identity]
    run_id: Annotated[str, strict_identity]
    status: str
    input: Annotated[dict[str, Any], merge_maps]
    completed_nodes: Annotated[list[str], append_unique]
    node_outputs: Annotated[dict[str, Any], merge_maps]
    agent_outputs: Annotated[dict[str, Any], merge_maps]
    evidence_ids: Annotated[list[str], append_unique]
    citation_ids: Annotated[list[str], append_unique]
    approval_ids: Annotated[list[str], append_unique]
    errors: Annotated[list[dict[str, Any]], append_unique]
    runtime_events: Annotated[list[dict[str, Any]], append_unique]
    final_output: Annotated[dict[str, Any], merge_maps]
    supervisor_decision: Annotated[dict[str, Any], merge_maps]
    plan: Annotated[dict[str, Any], merge_maps]
    github_evidence: Annotated[dict[str, Any], merge_maps]
    rag_evidence: dict[str, Any]
    runtime_evidence: Annotated[dict[str, Any], merge_maps]
    visual_evidence: Annotated[dict[str, Any], merge_maps]
    fused_evidence: Annotated[dict[str, Any], merge_maps]
    rca_result: Annotated[dict[str, Any], merge_maps]
    critic_result: Annotated[dict[str, Any], merge_maps]
    claim_verification: Annotated[dict[str, Any], merge_maps]
    citation_validation: Annotated[dict[str, Any], merge_maps]
    approval_state: Annotated[dict[str, Any], merge_maps]
    retry_count: int
    final_answer: Annotated[dict[str, Any], merge_maps]
    last_error: dict[str, Any]
    recovery: Annotated[dict[str, Any], merge_maps]
    graph_budget: dict[str, Any]
    supervisor_route_state: dict[str, Any]


@dataclass(frozen=True)
class StateMigrationResult:
    state: dict[str, Any]
    from_version: int
    to_version: int
    applied_steps: tuple[str, ...]


def _v1_to_v2(state: dict[str, Any]) -> dict[str, Any]:
    upgraded = deepcopy(state)
    # LangGraph Production Runtime states had no explicit schema version and only node_outputs/errors.
    upgraded.setdefault("agent_outputs", {})
    upgraded.setdefault("evidence_ids", [])
    upgraded.setdefault("approval_ids", [])
    upgraded.setdefault("runtime_events", [])
    upgraded["state_schema_version"] = 2
    return upgraded


def _v2_to_v3(state: dict[str, Any]) -> dict[str, Any]:
    upgraded = deepcopy(state)
    upgraded.setdefault("citation_ids", [])
    upgraded.setdefault("final_output", {})
    upgraded["state_schema_version"] = 3
    return upgraded


def _v3_to_v4(state: dict[str, Any]) -> dict[str, Any]:
    upgraded = deepcopy(state)
    for key in ("supervisor_decision", "plan", "github_evidence", "rag_evidence", "runtime_evidence", "visual_evidence", "fused_evidence", "rca_result", "critic_result", "claim_verification", "approval_state", "final_answer", "last_error", "recovery", "graph_budget", "supervisor_route_state"):
        upgraded.setdefault(key, {})
    upgraded.setdefault("retry_count", 0)
    upgraded["state_schema_version"] = 4
    return upgraded

def _v4_to_v5(state: dict[str, Any]) -> dict[str, Any]:
    upgraded=deepcopy(state);upgraded.setdefault("citation_validation",{});upgraded["state_schema_version"]=5;return upgraded


_MIGRATIONS = {
    1: (2, "v1_to_v2_parallel_state", _v1_to_v2),
    2: (3, "v2_to_v3_citation_state", _v2_to_v3),
    3: (4, "v3_to_v4_business_graph_state", _v3_to_v4),
    4: (5, "v4_to_v5_mandatory_citation_validation", _v4_to_v5),
}


def migrate_state(raw_state: Mapping[str, Any], *, target_version: int = CURRENT_STATE_SCHEMA_VERSION) -> StateMigrationResult:
    state = deepcopy(dict(raw_state))
    from_version = int(state.get("state_schema_version") or 1)
    if from_version < 1:
        raise StateMigrationError("state schema version must be >= 1")
    if from_version > target_version:
        raise StateMigrationError(
            f"cannot load future state schema v{from_version}; runtime supports v{target_version}"
        )
    applied: list[str] = []
    current = from_version
    while current < target_version:
        migration = _MIGRATIONS.get(current)
        if migration is None:
            raise StateMigrationError(f"no state migration registered from v{current}")
        next_version, name, func = migration
        state = func(state)
        current = next_version
        applied.append(name)
    state["state_schema_version"] = target_version
    _validate_core_identity(state)
    return StateMigrationResult(
        state=state,
        from_version=from_version,
        to_version=target_version,
        applied_steps=tuple(applied),
    )


def _validate_core_identity(state: Mapping[str, Any]) -> None:
    # investigation_id is workflow-specific; LangGraph materializes absent typed
    # string channels as "" in checkpoints used by non-investigation graphs.
    for key in ("tenant_id", "run_id"):
        if key in state and state[key] in (None, ""):
            raise StateMigrationError(f"state identity field cannot be empty: {key}")


@dataclass(frozen=True)
class StateEncryptionPolicy:
    version: str = STATE_ENCRYPTION_POLICY_VERSION
    # State persists identifiers/references, never credential material. Infrastructure
    # encryption-at-rest remains mandatory for production PostgreSQL backups/volumes.
    forbidden_key_fragments: tuple[str, ...] = (
        "password",
        "api_key",
        "apikey",
        "access_token",
        "refresh_token",
        "private_key",
        "secret_key",
        "authorization_header",
        "bearer_token",
    )

    def validate(self, state: Mapping[str, Any]) -> None:
        violations: list[str] = []

        def walk(value: Any, path: str) -> None:
            if isinstance(value, Mapping):
                for key, item in value.items():
                    key_text = str(key).lower()
                    next_path = f"{path}.{key}" if path else str(key)
                    if any(fragment in key_text for fragment in self.forbidden_key_fragments):
                        # Empty/null placeholders are allowed; actual secret material is not.
                        if item not in (None, "", [], {}):
                            violations.append(next_path)
                    walk(item, next_path)
            elif isinstance(value, list):
                for index, item in enumerate(value):
                    walk(item, f"{path}[{index}]")

        walk(state, "")
        if violations:
            raise ValueError(
                "checkpoint state contains secret material; persist a secret/object reference instead: "
                + ", ".join(sorted(violations))
            )


DEFAULT_STATE_ENCRYPTION_POLICY = StateEncryptionPolicy()


def prepare_state_for_checkpoint(raw_state: Mapping[str, Any]) -> StateMigrationResult:
    migrated = migrate_state(raw_state)
    DEFAULT_STATE_ENCRYPTION_POLICY.validate(migrated.state)
    # Canonical serialization is deliberately exercised before checkpoint persistence.
    canonical_state_json(migrated.state)
    return migrated
