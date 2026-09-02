from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

from fastapi.testclient import TestClient

from services.ai.main import app
from services.ai.topology import get_topology_service
from verideploy.topology.repository import InMemoryTopologyRepository
from verideploy.topology.seed import TENANT_ID, build_nexuspay_topology
from verideploy.topology.service import TopologyService
from verideploy.topology.validation import validate_topology

ROOT = Path(__file__).resolve().parents[2]
SEED_FILE = ROOT / "data" / "topology" / "nexuspay-topology.json"


def test_seed_is_stable_and_content_addressed():
    first = build_nexuspay_topology(); second = build_nexuspay_topology()
    assert first == second
    assert first.seed_sha256 == "752445f6036fddab83c2028f6c7d82ae78af72a9f25019cc3211baa3cfe77f44"


def test_topology_gate_counts_and_invariants_pass():
    report = validate_topology(build_nexuspay_topology())
    assert report.valid is True
    assert (report.team_count, report.owner_count, report.service_count) == (5, 5, 10)
    assert (report.dependency_count, report.environment_count, report.slo_count, report.deployment_count) == (12, 3, 20, 30)
    assert report.errors == ()


def test_every_team_has_owner_and_every_service_has_production_slo_and_deployment():
    snapshot = build_nexuspay_topology(); prod = next(env for env in snapshot.environments if env.name == "production")
    owner_teams = {owner.team_id for owner in snapshot.owners}
    assert owner_teams == {team.team_id for team in snapshot.teams}
    services = {service.service_id for service in snapshot.services}
    assert services == {slo.service_id for slo in snapshot.slos if slo.environment_id == prod.environment_id}
    assert services == {dep.service_id for dep in snapshot.deployments if dep.environment_id == prod.environment_id}


def test_dependency_edges_are_valid_and_non_self():
    snapshot = build_nexuspay_topology(); ids = {service.service_id for service in snapshot.services}
    assert all(dep.source_service_id in ids and dep.target_service_id in ids for dep in snapshot.dependencies)
    assert all(dep.source_service_id != dep.target_service_id for dep in snapshot.dependencies)


def test_seed_json_matches_generator_exactly():
    stored = json.loads(SEED_FILE.read_text())
    generated = build_nexuspay_topology().model_dump(mode="json")
    assert stored == generated


def test_in_memory_persistence_is_idempotent():
    repo = InMemoryTopologyRepository(); service = TopologyService(repo); snapshot = build_nexuspay_topology()
    assert service.seed(snapshot) == snapshot
    assert service.seed(snapshot) == snapshot
    assert service.get(tenant_id=TENANT_ID) == snapshot


def test_wrong_tenant_cannot_read_seeded_topology():
    repo = InMemoryTopologyRepository(); service = TopologyService(repo); service.seed(build_nexuspay_topology())
    assert service.get(tenant_id=UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")) is None


def test_private_api_requires_trusted_service_and_tenant_scope():
    repo = InMemoryTopologyRepository(); service = TopologyService(repo); service.seed(build_nexuspay_topology())
    app.dependency_overrides[get_topology_service] = lambda: service
    try:
        client = TestClient(app)
        assert client.get("/internal/v1/topology/nexuspay", headers={"x-tenant-id": str(TENANT_ID)}).status_code == 401
        ok = client.get("/internal/v1/topology/nexuspay", headers={"x-internal-service":"verideploy-gateway","x-tenant-id":str(TENANT_ID)})
        assert ok.status_code == 200 and ok.json()["company"]["name"] == "NexusPay"
        other = client.get("/internal/v1/topology/nexuspay", headers={"x-internal-service":"verideploy-gateway","x-tenant-id":"aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"})
        assert other.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_migration_contains_normalized_tables_and_forced_rls():
    source = (ROOT / "src/verideploy/database/migrations/versions/0010_nexuspay_topology.py").read_text()
    for table in ("topology_companies","topology_teams","topology_owners","topology_environments","topology_services","topology_dependencies","topology_slos","topology_deployments"):
        assert table in source
    assert "FORCE ROW LEVEL SECURITY" in source
    assert "source_service_id <> target_service_id" in source


def test_gateway_exposes_topology_without_browser_private_ai_call():
    module = (ROOT / "apps/gateway/src/app.module.ts").read_text()
    controller = (ROOT / "apps/gateway/src/topology/topology.controller.ts").read_text()
    service = (ROOT / "apps/gateway/src/topology/topology.service.ts").read_text()
    assert "TopologyModule" in module
    assert '@Controller("topology")' in controller
    assert "/internal/v1/topology/nexuspay" in service
    assert "PrivateAiClient" in service
    shared=(ROOT / "apps/gateway/src/boundary/private-ai.client.ts").read_text()
    assert '"x-internal-service":this.serviceName' in shared and 'private readonly serviceName="verideploy-gateway"' in shared


def test_frontend_renders_services_owners_slos_deployments_and_dependencies():
    page = (ROOT / "apps/web/app/(platform)/topology/page.tsx").read_text()
    assert "{data.company.name} Service Topology" in page
    assert "serviceGrid" in page and "dependencyList" in page
    assert "Deployments" in page and "Owner" in page and "Runtime" in page
    assert "/api/v1/topology/nexuspay" in page
    assert "/internal/v1/topology" not in page


def test_seed_script_uses_postgres_repository_not_test_memory():
    source = (ROOT / "scripts/seed_nexuspay_topology.py").read_text()
    assert "PostgresTopologyRepository" in source
    assert "TopologyService" in source
    assert "requires PostgreSQL" in source
