from __future__ import annotations

from pathlib import Path

import yaml

from scripts.validate_kubernetes import CHART, validate
from verideploy.platform.kubernetes import evaluate_workloads, simulate_single_pod_failure, simulate_single_zone_failure

ROOT = Path(__file__).resolve().parents[2]


def values():
    return yaml.safe_load((CHART / "values.yaml").read_text())


def test_production_chart_has_four_resilient_workloads() -> None:
    items = evaluate_workloads(values())
    assert set(items) == {"web", "gateway", "ai-service", "worker"}
    assert all(item.replicas >= 3 for item in items.values())
    assert all(item.min_available >= 2 for item in items.values())
    assert all(item.has_resources and item.has_probes for item in items.values())


def test_single_pod_failure_preserves_pdb_availability() -> None:
    result = simulate_single_pod_failure(values())
    assert result.passed
    assert all(result.workload_results.values())


def test_three_az_distribution_survives_one_zone_loss() -> None:
    result = simulate_single_zone_failure(values(), zones=3)
    assert result.passed
    assert all(result.workload_results.values())


def test_canary_and_migration_paths_are_explicit_and_safe() -> None:
    canary = (CHART / "templates/canary.yaml").read_text()
    migration = (CHART / "templates/migration-job.yaml").read_text()
    deploy_script = (ROOT / "scripts/deploy/canary.sh").read_text()
    assert "verideploy-gateway-canary" in canary
    assert "max-traffic-percent" in canary
    assert "pre-install,pre-upgrade" in migration
    assert '["alembic", "upgrade", "head"]' in migration
    assert "helm rollback" in deploy_script
    assert "--atomic" in deploy_script


def test_deployment_validation_gate_passes() -> None:
    report = validate()
    assert report["passed"] is True
    assert report["findings"] == []
    assert report["production_images_pinned"] is True
