from __future__ import annotations
import json
from collections import Counter
from pathlib import Path

from verideploy.incidents.generator import build_incident_dataset
from verideploy.incidents.schemas import FailureMode, IncidentDataset
from verideploy.incidents.validation import validate_incident_dataset
from verideploy.topology.seed import build_nexuspay_topology

ROOT = Path(__file__).resolve().parents[2]


def test_dataset_has_at_least_200_incidents_and_all_labels():
    dataset = build_incident_dataset()
    assert len(dataset.incidents) == 240
    assert {i.failure_mode for i in dataset.incidents} == set(FailureMode)


def test_labels_are_balanced():
    counts = Counter(i.failure_mode for i in build_incident_dataset().incidents)
    assert set(counts.values()) == {30}


def test_each_incident_has_release_metrics_logs_traces_timeline_resolution():
    for incident in build_incident_dataset().incidents:
        assert incident.release.commit_sha
        assert incident.metrics and incident.logs and incident.traces and incident.timeline
        assert incident.resolution.action


def test_causal_and_noise_evidence_are_both_present():
    for incident in build_incident_dataset().incidents:
        assert any(x.causal for x in incident.metrics) and any(not x.causal for x in incident.metrics)
        assert any(x.causal for x in incident.logs) and any(not x.causal for x in incident.logs)
        assert any(x.causal for x in incident.traces) and any(not x.causal for x in incident.traces)


def test_timelines_are_strictly_ordered():
    dataset = build_incident_dataset()
    for incident in dataset.incidents:
        times = [e.timestamp for e in incident.timeline]
        assert times == sorted(times)
        assert incident.started_at <= incident.detected_at <= incident.resolved_at


def test_deterministic_reproduction():
    a = build_incident_dataset()
    b = build_incident_dataset()
    assert a.dataset_sha256 == b.dataset_sha256
    assert a.model_dump(mode="json") == b.model_dump(mode="json")


def test_links_only_to_topology():
    dataset = build_incident_dataset()
    topology = build_nexuspay_topology()
    service_ids = {s.service_id for s in topology.services}
    env_ids = {e.environment_id for e in topology.environments}
    deployment_ids = {d.deployment_id for d in topology.deployments}
    assert dataset.topology_sha256 == topology.seed_sha256
    for incident in dataset.incidents:
        assert incident.primary_service_id in service_ids
        assert incident.environment_id in env_ids
        assert incident.release.deployment_id in deployment_ids


def test_train_validation_test_coverage_and_no_family_overlap():
    dataset = build_incident_dataset()
    splits = {i.split.value for i in dataset.incidents}
    assert splits == {"train", "validation", "test"}
    families = [(i.family_id, i.split.value) for i in dataset.incidents]
    assert len({f for f, _ in families}) == len(families)


def test_observable_features_do_not_contain_machine_label():
    for incident in build_incident_dataset().incidents:
        observable = " ".join([*(m.metric for m in incident.metrics), *(l.message for l in incident.logs), *(t.operation for t in incident.traces), *(e.summary for e in incident.timeline), incident.trigger_summary]).lower()
        assert incident.failure_mode.value not in observable


def test_validation_gate_passes_checked_in_dataset():
    payload = json.loads((ROOT / "data/incidents/nexuspay-incidents.json").read_text())
    report = validate_incident_dataset(IncidentDataset.model_validate(payload))
    assert report.valid, report.errors
    assert report.incident_count == 240


def test_validator_rejects_hash_tampering():
    dataset = build_incident_dataset()
    broken = dataset.model_copy(update={"dataset_sha256": "0" * 64})
    report = validate_incident_dataset(broken)
    assert not report.valid
    assert "dataset SHA-256 mismatch" in report.errors


def test_migration_has_rls_and_constraints():
    migration = (ROOT / "src/verideploy/database/migrations/versions/0011_synthetic_incidents.py").read_text()
    assert "FORCE ROW LEVEL SECURITY" in migration
    assert "synthetic_incidents_tenant_isolation" in migration
    assert "ck_synthetic_incident_failure_mode" in migration


def test_seed_script_uses_validated_checked_in_dataset():
    script = (ROOT / "scripts/seed_incident_dataset.py").read_text()
    assert "validate_incident_dataset" in script
    assert "nexuspay-incidents.json" in script
