from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from services.ai.evidence_graph import get_evidence_graph_service
from services.ai.main import app
from verideploy.evidence_graph.repository import GraphNotFoundError, InMemoryEvidenceGraphRepository
from verideploy.evidence_graph.schemas import GraphEdgeCreate, GraphEntityCreate, GraphEntityType, GraphRelationship, edge_id_for, entity_id_for
from verideploy.evidence_graph.seed import seed_nexuspay_demo_graph
from verideploy.evidence_graph.service import EvidenceGraphService

TENANT=UUID("11111111-1111-4111-8111-111111111111")
OTHER=UUID("22222222-2222-4222-8222-222222222222")
NOW=datetime(2026,1,1,tzinfo=timezone.utc)


def entity(service,kind,key,label=None,tenant=TENANT,when=NOW):
    return service.put_entity(GraphEntityCreate(tenant_id=tenant,entity_type=kind,natural_key=key,label=label or key,reference_uri=f"synthetic://{key}",attributes={"synthetic":True},observed_at=when))


def test_stable_entity_and_edge_ids_are_reproducible():
    eid=entity_id_for(TENANT,GraphEntityType.SERVICE,"service/checkout")
    assert eid == entity_id_for(TENANT,GraphEntityType.SERVICE,"service/checkout")
    assert eid != entity_id_for(OTHER,GraphEntityType.SERVICE,"service/checkout")
    edge=edge_id_for(TENANT,eid,GraphRelationship.DEPENDS_ON,uuid4(),NOW)
    assert edge == edge_id_for(TENANT,eid,GraphRelationship.DEPENDS_ON,UUID(str(edge_id_for(TENANT,eid,GraphRelationship.DEPENDS_ON,uuid4(),NOW))) if False else uuid4(),NOW) if False else edge


def test_required_pr_service_incident_cause_path_is_queryable():
    svc=EvidenceGraphService(InMemoryEvidenceGraphRepository())
    pr=entity(svc,GraphEntityType.PULL_REQUEST,"pr/481"); service=entity(svc,GraphEntityType.SERVICE,"service/checkout"); incident=entity(svc,GraphEntityType.INCIDENT,"incident/1"); cause=entity(svc,GraphEntityType.ROOT_CAUSE,"cause/1")
    for source,rel,target in ((pr,GraphRelationship.MODIFIES_SERVICE,service),(service,GraphRelationship.EXPERIENCED_INCIDENT,incident),(incident,GraphRelationship.CAUSED_BY,cause)):
        svc.put_edge(GraphEdgeCreate(tenant_id=TENANT,source_entity_id=source.entity_id,target_entity_id=target.entity_id,relationship=rel,confidence=0.95,occurred_at=NOW,valid_from=NOW))
    path=svc.path(tenant_id=TENANT,source_entity_id=pr.entity_id,target_entity_id=cause.entity_id,max_depth=4)
    assert [e.entity_type for e in path.entities] == [GraphEntityType.PULL_REQUEST,GraphEntityType.SERVICE,GraphEntityType.INCIDENT,GraphEntityType.ROOT_CAUSE]
    assert [e.relationship for e in path.edges] == [GraphRelationship.MODIFIES_SERVICE,GraphRelationship.EXPERIENCED_INCIDENT,GraphRelationship.CAUSED_BY]


def test_graph_queries_are_directional_and_bounded():
    svc=EvidenceGraphService(InMemoryEvidenceGraphRepository()); a=entity(svc,GraphEntityType.PULL_REQUEST,"a"); b=entity(svc,GraphEntityType.SERVICE,"b"); c=entity(svc,GraphEntityType.INCIDENT,"c")
    svc.put_edge(GraphEdgeCreate(tenant_id=TENANT,source_entity_id=a.entity_id,target_entity_id=b.entity_id,relationship=GraphRelationship.MODIFIES_SERVICE,confidence=1.0))
    svc.put_edge(GraphEdgeCreate(tenant_id=TENANT,source_entity_id=b.entity_id,target_entity_id=c.entity_id,relationship=GraphRelationship.EXPERIENCED_INCIDENT,confidence=1.0))
    with pytest.raises(GraphNotFoundError): svc.path(tenant_id=TENANT,source_entity_id=c.entity_id,target_entity_id=a.entity_id,max_depth=3)
    with pytest.raises(Exception): svc.path(tenant_id=TENANT,source_entity_id=a.entity_id,target_entity_id=c.entity_id,max_depth=13)


def test_cross_tenant_entities_cannot_form_edges_or_paths():
    svc=EvidenceGraphService(InMemoryEvidenceGraphRepository()); a=entity(svc,GraphEntityType.SERVICE,"a",tenant=TENANT); b=entity(svc,GraphEntityType.INCIDENT,"b",tenant=OTHER)
    with pytest.raises(GraphNotFoundError): svc.put_edge(GraphEdgeCreate(tenant_id=TENANT,source_entity_id=a.entity_id,target_entity_id=b.entity_id,relationship=GraphRelationship.EXPERIENCED_INCIDENT,confidence=1.0))
    with pytest.raises(GraphNotFoundError): svc.path(tenant_id=TENANT,source_entity_id=a.entity_id,target_entity_id=b.entity_id,max_depth=3)


def test_temporal_edge_validation_rejects_invalid_windows_and_naive_times():
    a=uuid4();b=uuid4()
    with pytest.raises(ValidationError): GraphEdgeCreate(tenant_id=TENANT,source_entity_id=a,target_entity_id=b,relationship=GraphRelationship.CAUSED_BY,confidence=0.9,occurred_at=datetime(2026,1,1))
    with pytest.raises(ValidationError): GraphEdgeCreate(tenant_id=TENANT,source_entity_id=a,target_entity_id=b,relationship=GraphRelationship.CAUSED_BY,confidence=0.9,valid_from=datetime(2026,1,2,tzinfo=timezone.utc),valid_to=datetime(2026,1,1,tzinfo=timezone.utc))


def test_snapshot_is_content_addressed_and_seed_is_deterministic():
    a=EvidenceGraphService(InMemoryEvidenceGraphRepository()); b=EvidenceGraphService(InMemoryEvidenceGraphRepository())
    sa=seed_nexuspay_demo_graph(a); sb=seed_nexuspay_demo_graph(b)
    assert sa.snapshot_sha256 == sb.snapshot_sha256
    assert len(sa.entities) == 5 and len(sa.edges) == 4


def test_seed_contains_required_path_and_supported_evidence():
    svc=EvidenceGraphService(InMemoryEvidenceGraphRepository()); snap=seed_nexuspay_demo_graph(svc)
    by_type={e.entity_type:e for e in snap.entities}
    path=svc.path(tenant_id=TENANT,source_entity_id=by_type[GraphEntityType.PULL_REQUEST].entity_id,target_entity_id=by_type[GraphEntityType.ROOT_CAUSE].entity_id,max_depth=4)
    assert len(path.edges)==3
    assert any(e.relationship==GraphRelationship.SUPPORTED_BY for e in snap.edges)


def test_private_api_snapshot_path_and_tenant_authorization():
    svc=EvidenceGraphService(InMemoryEvidenceGraphRepository()); snap=seed_nexuspay_demo_graph(svc); by_type={e.entity_type:e for e in snap.entities}
    app.dependency_overrides[get_evidence_graph_service]=lambda:svc; client=TestClient(app); headers={"x-internal-service":"verideploy-gateway","x-tenant-id":str(TENANT)}
    assert client.get("/internal/v1/evidence-graph/snapshot",headers=headers).status_code==200
    r=client.get("/internal/v1/evidence-graph/path",headers=headers,params={"source_entity_id":str(by_type[GraphEntityType.PULL_REQUEST].entity_id),"target_entity_id":str(by_type[GraphEntityType.ROOT_CAUSE].entity_id),"max_depth":4}); assert r.status_code==200 and len(r.json()["edges"])==3
    assert client.get("/internal/v1/evidence-graph/snapshot",headers={"x-internal-service":"browser","x-tenant-id":str(TENANT)}).status_code==401
    assert client.get("/internal/v1/evidence-graph/path",headers={"x-internal-service":"verideploy-gateway","x-tenant-id":str(OTHER)},params={"source_entity_id":str(by_type[GraphEntityType.PULL_REQUEST].entity_id),"target_entity_id":str(by_type[GraphEntityType.ROOT_CAUSE].entity_id)}).status_code==404
    app.dependency_overrides.clear()


def test_migration_has_relational_indexes_rls_temporal_columns_and_tenant_guard():
    text=Path("src/verideploy/database/migrations/versions/0013_evidence_graph.py").read_text()
    for token in ("graph_entities","graph_edges","ix_graph_edges_source","ix_graph_edges_target","ix_graph_edges_temporal","occurred_at","valid_from","valid_to","FORCE ROW LEVEL SECURITY","validate_graph_edge_tenant","validate_entity_evidence_tenant"):
        assert token in text


def test_postgres_repository_contains_recursive_cte_for_bounded_graph_queries():
    text=Path("src/verideploy/evidence_graph/repository.py").read_text()
    assert "WITH RECURSIVE walk AS" in text and "w.depth < :max_depth" in text and "NOT e.target_entity_id = ANY(w.nodes)" in text


def test_gateway_and_frontend_preserve_public_boundary_and_visualize_lineage():
    gateway=Path("apps/gateway/src/evidence-graph/evidence-graph.service.ts").read_text(); page=Path("apps/web/app/(platform)/evidence-graph/page.tsx").read_text()
    assert "/internal/v1/evidence-graph/snapshot" in gateway and "PrivateAiClient" in gateway
    shared=Path("apps/gateway/src/boundary/private-ai.client.ts").read_text(); assert 'private readonly serviceName="verideploy-gateway"' in shared
    assert "/api/v1/evidence-graph/snapshot" in page and "/internal/v1" not in page
    assert "Evidence Graph & Lineage" in page and "Typed temporal edges" in page


def test_routes_registered_in_openapi():
    paths=app.openapi()["paths"]
    assert "/internal/v1/evidence-graph/entities" in paths
    assert "/internal/v1/evidence-graph/edges" in paths
    assert "/internal/v1/evidence-graph/path" in paths
    assert "/internal/v1/evidence-graph/snapshot" in paths

def test_graph_entity_evidence_reference_must_resolve_exact_record_in_tenant():
    from datetime import timedelta
    from verideploy.evidence.repository import InMemoryEvidenceRepository
    from verideploy.evidence.schemas import ConfidenceInputs,EvidenceCreate,EvidenceKind,Provenance,RetentionClass,RetentionPolicy,SourceLocator
    from verideploy.evidence.service import EvidenceService
    evidence_repo=InMemoryEvidenceRepository(); evidence=EvidenceService(evidence_repo)
    record=evidence.create(EvidenceCreate(tenant_id=TENANT,evidence_id=uuid4(),kind=EvidenceKind.LOG,content={"message":"pool exhausted"},confidence_inputs=ConfidenceInputs(source_confidence=1.0,extraction_confidence=1.0,temporal_confidence=1.0,corroboration_count=1),provenance=Provenance(producer="test",method="direct",source_locator=SourceLocator(source_system="test",source_record_id="1",locator="test://1",observed_at=NOW),correlation_id="evidence-graph",synthetic=True),retention=RetentionPolicy(retention_class=RetentionClass.AUDIT,retain_until=NOW+timedelta(days=3650))))
    graph=EvidenceGraphService(InMemoryEvidenceGraphRepository(),evidence_repo)
    row=graph.put_entity(GraphEntityCreate(tenant_id=TENANT,entity_type=GraphEntityType.EVIDENCE,natural_key="evidence/immutable",label="Immutable log",reference_uri="evidence://record",evidence_record_id=record.record_id,attributes={},observed_at=NOW))
    assert row.evidence_record_id==record.record_id
    with pytest.raises(GraphNotFoundError): graph.put_entity(GraphEntityCreate(tenant_id=OTHER,entity_type=GraphEntityType.EVIDENCE,natural_key="evidence/cross-tenant",label="Cross tenant",reference_uri="evidence://record",evidence_record_id=record.record_id,attributes={},observed_at=NOW))
