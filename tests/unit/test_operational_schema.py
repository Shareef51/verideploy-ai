from pathlib import Path
import pytest
from verideploy.operational_schema.catalog import OPERATIONAL_SCHEMA_CATALOG, REQUIRED_SCHEMA_CONCEPTS, validate_schema_catalog
from verideploy.operational_schema.lifecycle import LifecycleKind, LifecycleTransitionError, allowed_transitions, validate_transition

MIG = Path("src/verideploy/database/migrations/versions/0014_complete_operational_schema.py")


def test_schema_catalog_covers_every_master_concept_without_duplicates():
    result = validate_schema_catalog()
    assert result["valid"] is True
    assert result["concept_count"] == 20
    assert set(REQUIRED_SCHEMA_CONCEPTS) == set(OPERATIONAL_SCHEMA_CATALOG)
    assert len({b.table for b in OPERATIONAL_SCHEMA_CATALOG.values()}) == 20


def test_reuses_existing_rag_visual_and_agent_run_tables():
    assert OPERATIONAL_SCHEMA_CATALOG["documents"].table == "retrieval_documents"
    assert OPERATIONAL_SCHEMA_CATALOG["chunks"].table == "retrieval_chunks"
    assert OPERATIONAL_SCHEMA_CATALOG["pages"].table == "visual_pages"
    assert OPERATIONAL_SCHEMA_CATALOG["visual_indexes"].table == "visual_page_indexes"
    assert OPERATIONAL_SCHEMA_CATALOG["agent_runs"].table == "agent_runs"


def test_investigation_lifecycle_accepts_only_declared_transitions():
    validate_transition(LifecycleKind.INVESTIGATION, "created", "collecting")
    validate_transition(LifecycleKind.INVESTIGATION, "analyzing", "review_required")
    with pytest.raises(LifecycleTransitionError): validate_transition(LifecycleKind.INVESTIGATION, "created", "completed")
    assert not allowed_transitions(LifecycleKind.INVESTIGATION, "completed")


def test_review_evaluation_and_job_terminal_states_fail_closed():
    validate_transition(LifecycleKind.REVIEW, "pending", "in_review")
    validate_transition(LifecycleKind.EVALUATION, "queued", "running")
    validate_transition(LifecycleKind.JOB, "running", "retry_wait")
    for kind, state in ((LifecycleKind.REVIEW,"approved"),(LifecycleKind.EVALUATION,"passed"),(LifecycleKind.JOB,"succeeded")):
        with pytest.raises(LifecycleTransitionError): validate_transition(kind, state, "running")


def test_migration_adds_all_missing_operational_tables():
    text=MIG.read_text()
    required=("releases","pull_requests","commits","incidents","investigations","investigation_checkpoints","human_reviews","tool_registry","model_registry","evaluations","feedback","jobs","outbox","inbox","audit_events")
    for table in required: assert table in text


def test_migration_enforces_lifecycle_transitions_and_terminal_state_integrity():
    text=MIG.read_text()
    assert "validate_lifecycle_transition" in text
    assert "BEFORE UPDATE OF status" in text
    assert "invalid lifecycle transition" in text
    assert 'for table in ("investigations","human_reviews","evaluations","jobs")' in text
    assert 'CREATE TRIGGER trg_{table}_lifecycle' in text


def test_outbox_and_inbox_are_idempotent_by_database_constraint():
    text=MIG.read_text()
    assert "uq_outbox_idempotency" in text
    assert "uq_inbox_message" in text


def test_schema_is_tenant_isolated_and_operationally_indexed():
    text=MIG.read_text()
    assert text.count("FORCE ROW LEVEL SECURITY") >= 1
    assert "_tenant_isolation" in text
    assert 'op.create_index(f"ix_{table}_operational"' in text
    for table in ("releases","incidents","jobs","audit_events"):
        assert f'"{table}": [' in text


def test_constraints_cover_core_data_quality_rules():
    text=MIG.read_text()
    for token in ("ck_incident_time","ck_evaluation_score","ck_feedback_rating","ck_job_attempts","ck_tool_risk","ck_model_role"):
        assert token in text


def test_migration_is_chained_after_and_reversible():
    text=MIG.read_text()
    assert 'down_revision = "0013_milestone31_evidence_graph"' in text
    assert "def downgrade()" in text and "DROP FUNCTION IF EXISTS validate_lifecycle_transition()" in text


def test_cross_tenant_operational_links_and_audit_mutation_are_blocked_in_database():
    text=MIG.read_text()
    assert "validate_tenant_link" in text
    assert "tenant link mismatch" in text
    assert "investigation_checkpoints" in text and "human_reviews" in text
    assert "block_audit_mutation" in text
    assert "BEFORE UPDATE OR DELETE ON audit_events" in text


def test_private_schema_catalog_route_is_authorized_and_complete():
    from fastapi.testclient import TestClient
    from services.ai.main import app
    client=TestClient(app)
    denied=client.get("/internal/v1/schema/catalog",headers={"x-internal-service":"browser"})
    assert denied.status_code==401
    response=client.get("/internal/v1/schema/catalog",headers={"x-internal-service":"verideploy-gateway"})
    assert response.status_code==200
    body=response.json(); assert body["valid"] is True and len(body["bindings"])==20
    assert {row["concept"] for row in body["bindings"]}==set(REQUIRED_SCHEMA_CONCEPTS)
