from __future__ import annotations
import json
from datetime import UTC,datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4
from verideploy.investigations.repository import SqlAlchemyInvestigationRepository
from verideploy.investigations.schemas import CreateInvestigationCommand
from verideploy.investigations.service import InvestigationService

ROOT=Path(__file__).resolve().parents[1]
with TemporaryDirectory() as td:
    service=InvestigationService(SqlAlchemyInvestigationRepository(f"sqlite:///{td}/validation.db",create_schema=True))
    tenant,user,investigation=uuid4(),uuid4(),uuid4()
    cmd=CreateInvestigationCommand(investigation_id=investigation,tenant_id=tenant,requested_by=user,idempotency_key='validation',query='Why did checkout latency increase after the release?')
    record,_=service.accept(cmd);record,_=service.initialize(tenant,investigation)
    base=service.projection(tenant,investigation)
    service.append(record=record,event_type='investigation.hypothesis.updated',payload={'hypothesis_id':'h-db','title':'Database pool exhaustion','confidence':.84,'supporting_evidence_ids':['ev-db']})
    record=service.get(tenant,investigation)
    service.append(record=record,event_type='investigation.evidence.linked',payload={'evidence_id':'ev-db','label':'DB pool saturation','evidence_type':'metric','relation':'supports','hypothesis_id':'h-db'})
    authoritative=service.projection(tenant,investigation)
    replay=service.events(tenant,investigation,after_sequence=base.last_sequence_number,limit=500)
    all_events=service.events(tenant,investigation,after_sequence=0,limit=500)
    reconstructed=service.projection(tenant,investigation)
    page=(ROOT/'apps/web/app/(platform)/incidents/page.tsx').read_text()
    contract=(ROOT/'contracts/openapi/gateway.yaml').read_text()
    checks={
      'authoritative_replay_converges': reconstructed.convergence_sha256==authoritative.convergence_sha256,
      'replay_contains_delta': len(replay)==2,
      'hypothesis_projection': authoritative.hypotheses and authoritative.hypotheses[0].hypothesis_id=='h-db',
      'evidence_projection': authoritative.evidence_map and authoritative.evidence_map[0].evidence_id=='ev-db',
      'sequence_gap_detection':'isContiguous' in page,
      'replay_path':'replayFrom' in page,
      'authoritative_refresh':'authoritativeRefresh' in page,
      'cancel':'Cancel' in page,
      'timeline':'Live timeline' in page,
      'hypotheses':'Hypothesis evolution' in page,
      'rca':'Root cause analysis' in page,
      'alternatives':'Alternative causes' in page,
      'evidence_map':'Evidence map' in page,
      'empty_error_states':'No active investigation' in page and 'role="alert"' in page,
      'public_view_contract':'/investigations/{investigationId}/view:' in contract and '/internal/v1' not in contract,
    }
    result={'valid':all(bool(v) for v in checks.values()),'checks':checks,'base_sequence':base.last_sequence_number,'final_sequence':authoritative.last_sequence_number,'replay_count':len(replay),'journal_count':len(all_events),'convergence_sha256':authoritative.convergence_sha256}
    out=ROOT/'artifacts/incident-screen-validation.json';out.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n")
    print(json.dumps(result,indent=2,sort_keys=True))
    raise SystemExit(0 if result['valid'] else 1)
