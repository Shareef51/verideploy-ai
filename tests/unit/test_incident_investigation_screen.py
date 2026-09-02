from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from verideploy.investigations.projection import project_investigation, projection_hash
from verideploy.investigations.schemas import CreateInvestigationCommand, InvestigationEvent
from verideploy.investigations.repository import SqlAlchemyInvestigationRepository
from verideploy.investigations.service import InvestigationService

ROOT=Path(__file__).resolve().parents[2]
WEB=ROOT/'apps/web'


def make_service(tmp_path):
    return InvestigationService(SqlAlchemyInvestigationRepository(f"sqlite:///{tmp_path/'.db'}",create_schema=True))


def make_running(tmp_path):
    service=make_service(tmp_path); tenant=uuid4(); investigation=uuid4(); user=uuid4()
    cmd=CreateInvestigationCommand(investigation_id=investigation,tenant_id=tenant,requested_by=user,idempotency_key='investigation-001',query='Why did checkout latency increase immediately after the production release?')
    record,_=service.accept(cmd); record,_=service.initialize(tenant,investigation)
    return service,tenant,investigation,record


def append(service,record,event_type,payload):
    return service.append(record=record,event_type=event_type,payload=payload)


def test_projection_reduces_hypothesis_rca_alternatives_and_evidence(tmp_path):
    service,tenant,investigation,record=make_running(tmp_path)
    append(service,record,'investigation.evidence.linked',{'evidence_id':'ev-1','label':'DB saturation trace','evidence_type':'trace','relation':'supports','hypothesis_id':'hyp-db','citation_id':'cit-1'})
    record=service.get(tenant,investigation)
    append(service,record,'investigation.hypothesis.updated',{'hypothesis_id':'hyp-db','title':'Connection pool exhaustion','status':'leading','confidence':.88,'supporting_evidence_ids':['ev-1']})
    record=service.get(tenant,investigation)
    append(service,record,'investigation.rca.updated',{'hypothesis_id':'hyp-db','summary':'Connection pool exhaustion caused checkout latency.','confidence':.91,'determined':True,'evidence_ids':['ev-1'],'alternatives':[{'hypothesis_id':'hyp-cache','summary':'Cache pressure','confidence':.24}]})
    projection=service.projection(tenant,investigation)
    assert projection.root_cause and projection.root_cause.determined and projection.root_cause.confidence==.91
    assert projection.hypotheses[0].hypothesis_id=='hyp-db' and projection.evidence_map[0].citation_id=='cit-1'
    assert projection.alternatives[0].hypothesis_id=='hyp-cache'
    assert projection.last_sequence_number==service.get(tenant,investigation).last_sequence_number


def test_projection_is_deterministic_under_event_input_order(tmp_path):
    service,tenant,investigation,record=make_running(tmp_path)
    append(service,record,'investigation.hypothesis.updated',{'hypothesis_id':'h1','title':'Database saturation','confidence':.7})
    record=service.get(tenant,investigation)
    append(service,record,'investigation.evidence.linked',{'evidence_id':'e1','label':'metric','hypothesis_id':'h1'})
    record=service.get(tenant,investigation); events=service.events(tenant,investigation,limit=500)
    a=project_investigation(record,events); b=project_investigation(record,list(reversed(events)))
    assert a.model_dump(mode='json')==b.model_dump(mode='json')
    assert a.convergence_sha256==b.convergence_sha256


def test_authoritative_refresh_and_replayed_event_state_converge(tmp_path):
    service,tenant,investigation,record=make_running(tmp_path)
    base_events=service.events(tenant,investigation,limit=500); base=project_investigation(record,base_events)
    append(service,record,'investigation.hypothesis.updated',{'hypothesis_id':'h1','title':'Schema lock contention','confidence':.81,'supporting_evidence_ids':['e2']})
    record=service.get(tenant,investigation)
    append(service,record,'investigation.evidence.linked',{'evidence_id':'e2','label':'migration lock trace','evidence_type':'trace','relation':'supports','hypothesis_id':'h1'})
    authoritative=service.projection(tenant,investigation)
    replay=service.events(tenant,investigation,after_sequence=base.last_sequence_number,limit=500)
    record=service.get(tenant,investigation)
    reconstructed=project_investigation(record,base_events+replay)
    assert reconstructed.convergence_sha256==authoritative.convergence_sha256
    assert reconstructed.model_dump(mode='json')==authoritative.model_dump(mode='json')


def test_projection_hash_changes_when_authoritative_state_changes(tmp_path):
    service,tenant,investigation,record=make_running(tmp_path); first=service.projection(tenant,investigation)
    append(service,record,'investigation.hypothesis.updated',{'hypothesis_id':'h1','title':'Network regression','confidence':.6})
    second=service.projection(tenant,investigation)
    assert first.convergence_sha256!=second.convergence_sha256
    assert len(second.convergence_sha256)==64


def test_private_and_public_view_routes_are_wired():
    private=(ROOT/'services/ai/routes/investigations.py').read_text(); controller=(ROOT/'apps/gateway/src/investigations/investigations.controller.ts').read_text(); service=(ROOT/'apps/gateway/src/investigations/investigations.service.ts').read_text()
    assert '@router.get("/{investigation_id}/view"' in private
    assert '@Get(":id/view")' in controller
    assert '/internal/v1/investigations/${encodeURIComponent(id)}/view' in service


def test_frontend_has_creation_timeline_hypothesis_rca_alternatives_evidence_and_cancel():
    page=(WEB/'app/(platform)/incidents/page.tsx').read_text()
    for text in ['Start investigation','Live timeline','Hypothesis evolution','Root cause analysis','Alternative causes','Evidence map','Cancel']:
        assert text in page
    assert '/api/v1/investigations' in page and '/internal/v1' not in page


def test_frontend_detects_sequence_gap_then_replays_and_authoritatively_reconciles():
    page=(WEB/'app/(platform)/incidents/page.tsx').read_text(); convergence=(WEB/'lib/investigations/convergence.ts').read_text()
    assert 'isContiguous' in page and 'replayFrom' in page and 'authoritativeRefresh' in page
    assert 'if(!isContiguous(base,event))' in page
    assert 'investigation event sequence gap' in convergence
    assert 'convergence_sha256' in convergence


def test_frontend_has_explicit_reconnect_and_empty_error_states():
    page=(WEB/'app/(platform)/incidents/page.tsx').read_text()
    for state in ['connecting','replaying','reconciling','disconnected']:
        assert state in page
    assert 'No active investigation' in page and 'role="alert"' in page and 'Reconcile' in page


def test_public_openapi_exposes_projection_but_no_private_python_route():
    contract=(ROOT/'contracts/openapi/gateway.yaml').read_text()
    assert '/investigations/{investigationId}/view:' in contract
    assert 'operationId: getInvestigationView' in contract
    assert '/internal/v1' not in contract
    import re
    match=re.search(r'^\s*version:\s*(\d+)\.(\d+)\.(\d+)\s*$',contract,re.M); assert match and tuple(map(int,match.groups())) >= (0,46,0)


def test_version_and_no_new_database_authority():
    import re
    match=re.search(r'(\d+)\.(\d+)\.(\d+)',(ROOT/'src/verideploy/__init__.py').read_text()); assert match and tuple(map(int,match.groups())) >= (0,46,0)
    assert not list((ROOT/'src/verideploy/database/migrations/versions').glob('*incident_investigation_screen*'))
    projection=(ROOT/'src/verideploy/investigations/projection.py').read_text()
    assert 'project_investigation' in projection and 'projection_hash' in projection
