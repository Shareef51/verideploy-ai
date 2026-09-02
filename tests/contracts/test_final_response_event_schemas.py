from __future__ import annotations
import copy
import importlib.util
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from verideploy.contracts.final_schemas import (
    CitationReference, EvidenceReference, FinalEventPayload, KafkaEventEnvelope,
    ReleaseRiskFinalResponse, ReviewResponse, ReviewStatus, RiskBand, RiskDecision,
    WebSocketEventEnvelope,
)

ROOT=Path(__file__).resolve().parents[2]

def evidence():
    return EvidenceReference(evidence_id="ev-1",kind="release",summary="Deployment changed pool size",provenance_id="prov-1",citation_ids=("cit-1",))

def citation():
    return CitationReference(citation_id="cit-1",evidence_id="ev-1",source_type="release",locator="release:v4.8.2")

def test_release_response_requires_resolvable_citations():
    response=ReleaseRiskFinalResponse(assessment_id=uuid4(),tenant_id=uuid4(),correlation_id=uuid4(),release_id="v4.8.2",score=82,risk_band=RiskBand.HIGH,decision=RiskDecision.DELAY,confidence=.94,summary="High migration risk",risk_factors=("migration",),recommended_actions=("review",),evidence=(evidence(),),citations=(citation(),),review=ReviewResponse(status=ReviewStatus.PENDING,required=True),completed_at=datetime.now(UTC))
    assert response.citations[0].evidence_id=="ev-1"

def test_websocket_and_kafka_envelopes_share_event_payload_contract():
    payload=FinalEventPayload(resource_type="release_risk",resource_id="assessment-1",status="COMPLETED",citation_ids=("cit-1",))
    common=dict(event_id=uuid4(),event_type="release_risk.completed",tenant_id=uuid4(),aggregate_id="assessment-1",correlation_id=uuid4(),sequence_number=7,payload=payload)
    ws=WebSocketEventEnvelope(**common,high_watermark=7,occurred_at=datetime.now(UTC))
    kafka=KafkaEventEnvelope(**common,ordering_key=f"{common['tenant_id']}:assessment-1",producer="release-worker")
    assert ws.payload.model_dump()==kafka.payload.model_dump()

def test_generator_is_deterministic_and_generated_clients_exist():
    subprocess.run([sys.executable,"scripts/generate_contracts.py"],cwd=ROOT,check=True,env={**__import__('os').environ,"PYTHONPATH":"src"})
    first=(ROOT/'contracts/final/manifest.json').read_bytes()
    subprocess.run([sys.executable,"scripts/generate_contracts.py"],cwd=ROOT,check=True,env={**__import__('os').environ,"PYTHONPATH":"src"})
    assert first==(ROOT/'contracts/final/manifest.json').read_bytes()
    assert (ROOT/'generated/clients/typescript/contracts.ts').exists()
    spec=importlib.util.spec_from_file_location('vd_generated',ROOT/'generated/clients/python/verideploy_contracts.py'); assert spec and spec.loader
    mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); assert hasattr(mod,'FinalEventPayload')

def test_backward_compatibility_detects_removed_field_and_enum_narrowing():
    sys.path.insert(0,str(ROOT/'scripts'))
    from generate_contracts import compare_signature, signature
    old=signature(ReleaseRiskFinalResponse.model_json_schema())
    new=copy.deepcopy(old)
    new['root']['properties'].pop('summary')
    new['defs']['RiskDecision']['enum'] = [x for x in new['defs']['RiskDecision']['enum'] if x != 'BLOCK']
    errors=compare_signature(old,new,'risk')
    assert any('removed properties' in x for x in errors)
    assert any('enum values removed' in x for x in errors)

def test_contract_manifest_covers_all_final_schema_families():
    manifest=json.loads((ROOT/'contracts/final/manifest.json').read_text())
    names=set(manifest['schemas'])
    assert {'release-risk-response.v1','rca-response.v1','evidence-reference.v1','timeline-entry.v1','review-response.v1','api-error.v1','websocket-envelope.v1','kafka-envelope.v1'} <= names
