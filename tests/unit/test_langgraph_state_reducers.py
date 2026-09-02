from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from verideploy.graphs.memory_repository import InMemoryGraphRuntimeRepository
from verideploy.graphs.runtime import GraphDefinition, GraphRegistry, GraphRunStatus, LangGraphRuntime
from verideploy.graphs.saved_state import InMemorySavedStateRepository
from verideploy.graphs.state import (
    CURRENT_STATE_SCHEMA_VERSION,
    StateEncryptionPolicy,
    StateMigrationError,
    StateReducerConflict,
    append_unique,
    canonical_state_json,
    merge_maps,
    migrate_state,
    state_sha256,
)


def _legacy_state() -> dict:
    return {
        "tenant_id": "11111111-1111-4111-8111-111111111111",
        "investigation_id": "inv-active-001",
        "run_id": "22222222-2222-4222-8222-222222222222",
        "correlation_id": "corr-active",
        "completed_nodes": ["intake"],
        "node_outputs": {"intake": {"incident_id": "INC-42"}},
        "errors": [],
        "input": {"incident_id": "INC-42"},
    }


def test_state_migration_v1_to_current_preserves_active_investigation_identity_and_outputs():
    legacy = _legacy_state()
    migrated = migrate_state(legacy)
    assert migrated.from_version == 1
    assert migrated.to_version == CURRENT_STATE_SCHEMA_VERSION == 5
    assert migrated.applied_steps == ("v1_to_v2_parallel_state", "v2_to_v3_citation_state", "v3_to_v4_business_graph_state", "v4_to_v5_mandatory_citation_validation")
    assert migrated.state["investigation_id"] == legacy["investigation_id"]
    assert migrated.state["run_id"] == legacy["run_id"]
    assert migrated.state["correlation_id"] == legacy["correlation_id"]
    assert migrated.state["completed_nodes"] == ["intake"]
    assert migrated.state["node_outputs"] == legacy["node_outputs"]
    assert migrated.state["agent_outputs"] == {}
    assert migrated.state["evidence_ids"] == []
    assert migrated.state["citation_ids"] == []
    assert migrated.state["approval_ids"] == []


def test_future_state_version_fails_closed():
    with pytest.raises(StateMigrationError, match="future state schema"):
        migrate_state({"state_schema_version": CURRENT_STATE_SCHEMA_VERSION + 1})


def test_parallel_append_reducer_is_deduplicated_and_branch_order_independent():
    left = ["evidence-b", "evidence-a"]
    right = ["evidence-c", "evidence-a"]
    assert append_unique(left, right) == append_unique(right, left)
    assert append_unique(left, right) == ["evidence-a", "evidence-b", "evidence-c"]


def test_parallel_map_reducer_merges_independent_outputs_and_rejects_conflicting_writes():
    branch_a = {"rag": {"status": "done", "evidence": 2}}
    branch_b = {"visual": {"status": "done"}}
    assert merge_maps(branch_a, branch_b) == merge_maps(branch_b, branch_a)
    assert merge_maps(branch_a, branch_b) == {
        "rag": {"status": "done", "evidence": 2},
        "visual": {"status": "done"},
    }
    with pytest.raises(StateReducerConflict, match="parallel state conflict"):
        merge_maps({"rag": {"status": "done"}}, {"rag": {"status": "failed"}})


def test_state_serialization_is_canonical_and_hash_stable():
    a = {"state_schema_version": 3, "node_outputs": {"b": 2, "a": 1}, "completed_nodes": ["b", "a"]}
    b = {"completed_nodes": ["b", "a"], "node_outputs": {"a": 1, "b": 2}, "state_schema_version": 3}
    assert canonical_state_json(a) == canonical_state_json(b)
    assert state_sha256(a) == state_sha256(b)
    assert len(state_sha256(a)) == 64


def test_encryption_policy_rejects_secret_material_but_allows_secret_references():
    policy = StateEncryptionPolicy()
    policy.validate({"state_schema_version": 3, "credential_ref": "vault://prod/github"})
    policy.validate({"state_schema_version": 3, "api_key": None})
    with pytest.raises(ValueError, match="persist a secret/object reference"):
        policy.validate({"state_schema_version": 3, "openai_api_key": "sk-not-for-checkpoint"})


def test_saved_state_repository_is_append_only_by_value_and_records_version_metadata():
    repository = InMemorySavedStateRepository()
    tenant, run_id = uuid4(), uuid4()
    original = _legacy_state()
    original["tenant_id"] = str(tenant); original["run_id"] = str(run_id)
    first = repository.save_snapshot(tenant_id=tenant, run_id=run_id, snapshot_kind="input", state=original)
    assert first.state_schema_version == CURRENT_STATE_SCHEMA_VERSION
    assert first.migration_history == ("v1_to_v2_parallel_state", "v2_to_v3_citation_state", "v3_to_v4_business_graph_state", "v4_to_v5_mandatory_citation_validation")
    assert len(first.state_sha256) == 64
    first.state["node_outputs"]["intake"]["incident_id"] = "MUTATED"
    stored = repository.latest_snapshot(tenant_id=tenant, run_id=run_id)
    assert stored is not None
    assert stored.state["node_outputs"]["intake"]["incident_id"] == "INC-42"


class MigrationAwareGraph:
    def __init__(self, checkpoint_state: dict) -> None:
        self.checkpoint_state = deepcopy(checkpoint_state)
        self.update_calls: list[dict] = []
        self.invoke_calls = 0

    async def aget_state(self, config):
        return SimpleNamespace(values=deepcopy(self.checkpoint_state))

    async def aupdate_state(self, config, values):
        self.checkpoint_state = deepcopy(values)
        self.update_calls.append(deepcopy(values))

    async def ainvoke(self, input, config=None, **kwargs):
        self.invoke_calls += 1
        merged = merge_maps(self.checkpoint_state.get("node_outputs", {}), {"resume": {"preserved": True}})
        self.checkpoint_state = {**self.checkpoint_state, **input, "node_outputs": merged, "completed_nodes": append_unique(self.checkpoint_state.get("completed_nodes"), ["resume"])}
        return deepcopy(self.checkpoint_state)

    async def astream(self, input, config=None, **kwargs):
        yield {"resume": {"status": "completed"}}


@pytest.mark.asyncio
async def test_runtime_upgrades_failed_active_checkpoint_before_resume_and_preserves_state():
    tenant, run_id = uuid4(), uuid4()
    legacy = _legacy_state()
    legacy["tenant_id"] = str(tenant); legacy["run_id"] = str(run_id)
    graph = MigrationAwareGraph(legacy)
    registry = GraphRegistry()
    registry.register(GraphDefinition(name="investigation", version="1", factory=lambda cp: graph))
    runtime_repo = InMemoryGraphRuntimeRepository()
    state_repo = InMemorySavedStateRepository()
    runtime = LangGraphRuntime(registry=registry, repository=runtime_repo, checkpointer=object(), saved_state_repository=state_repo)
    runtime_repo.create_run(tenant_id=tenant, run_id=run_id, thread_id=str(run_id), graph_name="investigation", graph_version="1", correlation_id="corr-active")
    runtime_repo.set_status(tenant_id=tenant, run_id=run_id, status=GraphRunStatus.FAILED)

    record, result = await runtime.execute(
        tenant_id=tenant,
        correlation_id="corr-active",
        graph_name="investigation",
        graph_version="1",
        input_state={"investigation_id": "inv-active-001", "input": {"incident_id": "INC-42"}},
        run_id=run_id,
        thread_id=str(run_id),
    )
    assert record.status == GraphRunStatus.COMPLETED
    assert graph.update_calls and graph.update_calls[0]["state_schema_version"] == 5
    assert result["investigation_id"] == "inv-active-001"
    assert result["node_outputs"]["intake"]["incident_id"] == "INC-42"
    assert result["node_outputs"]["resume"]["preserved"] is True
    assert "intake" in result["completed_nodes"] and "resume" in result["completed_nodes"]
    events = runtime_repo.list_events(tenant_id=tenant, run_id=run_id)
    migration_events = [e for e in events if e.event_type == "graph.state.migrated"]
    assert len(migration_events) == 1
    assert migration_events[0].payload["from_version"] == 1
    assert state_repo.latest_snapshot(tenant_id=tenant, run_id=run_id).state_schema_version == 5


def test_migration_has_rls_append_only_and_tenant_guard():
    migration = Path("src/verideploy/database/migrations/versions/0021_langgraph_state_reducers.py").read_text()
    assert 'revision = "0021_milestone39_langgraph_state_reducers"' in migration
    assert 'down_revision = "0020_milestone38_citation_architecture"' in migration
    assert "graph_state_snapshots" in migration
    assert "ENABLE ROW LEVEL SECURITY" in migration and "FORCE ROW LEVEL SECURITY" in migration
    assert "prevent_state_mutation" in migration
    assert "validate_state_run_tenant" in migration
    assert "state_schema_version" in migration and "state_sha256" in migration


def test_production_factory_wires_postgres_saved_state_repository_and_reference_only_policy():
    factory = Path("src/verideploy/graphs/factory.py").read_text()
    config = Path("src/verideploy/config.py").read_text()
    env = Path(".env.example").read_text()
    assert "PostgresSavedStateRepository" in factory
    assert "saved_state_repository=saved_state_repository" in factory
    assert "langgraph_state_encryption_policy" in config
    assert "LANGGRAPH_STATE_ENCRYPTION_POLICY=reference_only" in env
