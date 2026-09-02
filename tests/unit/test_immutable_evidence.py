from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from services.ai.evidence import get_evidence_service
from services.ai.main import app
from verideploy.evidence.repository import EvidenceConflictError, EvidenceNotFoundError, InMemoryEvidenceRepository
from verideploy.evidence.schemas import (
    ConfidenceInputs, EvidenceCreate, EvidenceKind, EvidenceParent, EvidenceVersionCreate, ObjectReference,
    ParentRelation, Provenance, RetentionClass, RetentionPolicy, SourceLocator, canonical_content_sha256,
)
from verideploy.evidence.service import EvidenceService

TENANT = UUID("10000000-0000-0000-0000-000000000030")
OTHER = UUID("20000000-0000-0000-0000-000000000030")


def common():
    now = datetime(2026, 8, 17, 18, 0, tzinfo=timezone.utc)
    return {
        "confidence_inputs": ConfidenceInputs(source_confidence=0.9, extraction_confidence=0.8, temporal_confidence=1.0, corroboration_count=2, notes=("direct",)),
        "provenance": Provenance(producer="importer", method="normalized", source_locator=SourceLocator(source_system="synthetic-incidents", source_record_id="INC-001", locator="incident://INC-001/log/1", observed_at=now), correlation_id="corr", synthetic=True),
        "retention": RetentionPolicy(retention_class=RetentionClass.AUDIT, retain_until=now + timedelta(days=2555), legal_hold=False),
    }


def create(service: EvidenceService, *, tenant=TENANT, evidence_id=None, content=None, parents=(), derived=False):
    return service.create(EvidenceCreate(tenant_id=tenant, evidence_id=evidence_id or uuid4(), kind=EvidenceKind.LOG,
        content=content or {"message":"pool exhausted","severity":"error"}, parents=parents, derived=derived, **common()))


def test_content_hash_is_canonical_and_stable():
    assert canonical_content_sha256({"b":2,"a":1}) == canonical_content_sha256({"a":1,"b":2})


def test_create_record_is_content_addressed_and_not_overwritten():
    repo=InMemoryEvidenceRepository(); svc=EvidenceService(repo); eid=uuid4()
    row=create(svc,evidence_id=eid)
    assert row.version == 1 and row.content_sha256 == canonical_content_sha256(row.content)
    with pytest.raises(EvidenceConflictError): create(svc,evidence_id=eid,content={"message":"changed"})
    assert svc.latest(tenant_id=TENANT,evidence_id=eid).content == row.content



def test_in_memory_persistence_is_not_silently_mutated_by_returned_payload():
    svc=EvidenceService(InMemoryEvidenceRepository()); row=create(svc,content={"nested":{"value":1}})
    row.content["nested"]["value"] = 99
    persisted=svc.get(tenant_id=TENANT,record_id=row.record_id)
    assert persisted.content["nested"]["value"] == 1
    assert persisted.content_sha256 == canonical_content_sha256({"nested":{"value":1}})

def test_version_is_append_only_and_links_immediate_previous_record():
    svc=EvidenceService(InMemoryEvidenceRepository()); first=create(svc)
    req=EvidenceVersionCreate(tenant_id=TENANT,evidence_id=first.evidence_id,previous_record_id=first.record_id,
        content={"message":"pool exhausted","severity":"critical"},**common())
    second=svc.create_version(req)
    assert second.version == 2 and second.record_id != first.record_id
    assert second.parents[0] == EvidenceParent(parent_record_id=first.record_id, relation=ParentRelation.VERSION_OF)
    assert [r.version for r in svc.versions(tenant_id=TENANT,evidence_id=first.evidence_id)] == [1,2]


def test_stale_version_parent_is_rejected():
    svc=EvidenceService(InMemoryEvidenceRepository()); first=create(svc)
    second=svc.create_version(EvidenceVersionCreate(tenant_id=TENANT,evidence_id=first.evidence_id,previous_record_id=first.record_id,content={"v":2},**common()))
    with pytest.raises(EvidenceConflictError):
        svc.create_version(EvidenceVersionCreate(tenant_id=TENANT,evidence_id=first.evidence_id,previous_record_id=first.record_id,content={"v":3},**common()))
    assert svc.latest(tenant_id=TENANT,evidence_id=first.evidence_id).record_id == second.record_id


def test_derived_evidence_requires_parent_and_lineage_is_bidirectional():
    svc=EvidenceService(InMemoryEvidenceRepository()); parent=create(svc)
    child=create(svc,parents=(EvidenceParent(parent_record_id=parent.record_id,relation=ParentRelation.EXTRACTED_FROM),),derived=True,content={"fact":"db pool maxed"})
    lineage=svc.lineage(tenant_id=TENANT,record_id=child.record_id)
    assert lineage.parents[0].record_id == parent.record_id
    assert svc.lineage(tenant_id=TENANT,record_id=parent.record_id).children[0].record_id == child.record_id
    with pytest.raises(ValidationError):
        EvidenceCreate(tenant_id=TENANT,evidence_id=uuid4(),kind=EvidenceKind.ANALYSIS,content={"x":1},derived=True,**common())


def test_cross_tenant_parent_is_not_visible_or_usable():
    svc=EvidenceService(InMemoryEvidenceRepository()); parent=create(svc,tenant=OTHER)
    with pytest.raises(EvidenceNotFoundError):
        create(svc,tenant=TENANT,parents=(EvidenceParent(parent_record_id=parent.record_id),),derived=True)
    with pytest.raises(EvidenceNotFoundError): svc.get(tenant_id=TENANT,record_id=parent.record_id)


def test_object_reference_hash_version_and_locator_are_preserved():
    svc=EvidenceService(InMemoryEvidenceRepository())
    ref=ObjectReference(uri="s3://evidence/tenant/log.json",sha256="a"*64,media_type="application/json",size_bytes=123,version_id="v-17")
    req=EvidenceCreate(tenant_id=TENANT,evidence_id=uuid4(),kind=EvidenceKind.DOCUMENT,content={"summary":"release record"},object_reference=ref,**common())
    row=svc.create(req)
    assert row.object_reference == ref
    assert row.provenance.source_locator.locator == "incident://INC-001/log/1"
    assert row.retention.retention_class == RetentionClass.AUDIT


def test_unsafe_object_reference_and_naive_retention_are_rejected():
    with pytest.raises(ValidationError): ObjectReference(uri="https://attacker.invalid/x",sha256="b"*64,media_type="text/plain",size_bytes=1)
    with pytest.raises(ValidationError): RetentionPolicy(retention_class=RetentionClass.OPERATING,retain_until=datetime(2027,1,1))


def test_api_create_version_read_and_lineage_with_tenant_scope():
    svc=EvidenceService(InMemoryEvidenceRepository()); app.dependency_overrides[get_evidence_service]=lambda: svc
    client=TestClient(app); eid=uuid4()
    body={
      "tenant_id":str(TENANT),"evidence_id":str(eid),"kind":"log","content":{"message":"timeout"},
      "confidence_inputs":{"source_confidence":0.9,"extraction_confidence":0.8,"temporal_confidence":1.0,"corroboration_count":1,"notes":[]},
      "provenance":{"producer":"test","method":"direct","source_locator":{"source_system":"loki","source_record_id":"r1","locator":"loki://r1","observed_at":"2026-08-17T18:00:00Z"},"correlation_id":"corr","synthetic":True},
      "retention":{"retention_class":"audit","retain_until":"2033-08-17T18:00:00Z","legal_hold":False},"parents":[],"derived":False,
    }
    headers={"x-internal-service":"verideploy-gateway","x-tenant-id":str(TENANT)}
    r=client.post("/internal/v1/evidence",json=body,headers=headers); assert r.status_code == 201, r.text
    first=r.json(); vbody=copy.deepcopy(body); vbody.pop("kind"); vbody.pop("parents"); vbody.pop("derived"); vbody["previous_record_id"]=first["record_id"]; vbody["content"]={"message":"timeout confirmed"}
    r=client.post(f"/internal/v1/evidence/{eid}/versions",json=vbody,headers=headers); assert r.status_code == 201, r.text
    second=r.json(); assert second["version"] == 2
    assert client.get(f"/internal/v1/evidence/records/{second['record_id']}/lineage",headers=headers).json()["parents"][0]["record_id"] == first["record_id"]
    assert client.get(f"/internal/v1/evidence/records/{first['record_id']}",headers={**headers,"x-tenant-id":str(OTHER)}).status_code == 404
    app.dependency_overrides.clear()


def test_api_rejects_untrusted_service_and_body_tenant_mismatch():
    svc=EvidenceService(InMemoryEvidenceRepository()); app.dependency_overrides[get_evidence_service]=lambda: svc
    client=TestClient(app); body={
      "tenant_id":str(TENANT),"evidence_id":str(uuid4()),"kind":"event","content":{"x":1},
      "confidence_inputs":{"source_confidence":1.0,"extraction_confidence":1.0,"temporal_confidence":1.0,"corroboration_count":0,"notes":[]},
      "provenance":{"producer":"test","method":"direct","source_locator":{"source_system":"x","source_record_id":"1","locator":"x://1"},"correlation_id":"c","synthetic":True},
      "retention":{"retention_class":"operating","retain_until":"2027-08-17T18:00:00Z","legal_hold":False},"parents":[],"derived":False,
    }
    assert client.post("/internal/v1/evidence",json=body,headers={"x-internal-service":"browser","x-tenant-id":str(TENANT)}).status_code == 401
    assert client.post("/internal/v1/evidence",json=body,headers={"x-internal-service":"verideploy-gateway","x-tenant-id":str(OTHER)}).status_code == 403
    app.dependency_overrides.clear()


def test_migration_contains_immutable_triggers_rls_and_deferred_lineage_gate():
    text=Path("src/verideploy/database/migrations/versions/0012_immutable_evidence.py").read_text()
    for token in ("evidence_versions","evidence_parent_links","FORCE ROW LEVEL SECURITY","forbid_evidence_mutation","BEFORE UPDATE OR DELETE","DEFERRABLE INITIALLY DEFERRED","validate_evidence_lineage","version_of"):
        assert token in text


def test_routes_registered_in_private_openapi():
    paths=app.openapi()["paths"]
    assert "/internal/v1/evidence" in paths
    assert "/internal/v1/evidence/{evidence_id}/versions" in paths
    assert "/internal/v1/evidence/records/{record_id}/lineage" in paths
