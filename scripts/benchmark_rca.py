from __future__ import annotations
import asyncio, json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from uuid import uuid4
from verideploy.agents.contracts import AgentAuthorization, AgentRequest, ToolPermission
from verideploy.agents.prompts import build_prompt_registry
from verideploy.agents.repository import InMemoryAgentRunRepository
from verideploy.agents.rca import RCAAgent
from verideploy.rag.fusion.schemas import EvidenceChannel, EvidenceLocator, NormalizedEvidence

class Model:
    def __init__(self, output): self.output=output
    async def generate(self, **kwargs): return kwargs['output_model'].model_validate(self.output)

def evidence(tenant, channel, title, content, minute):
    eid=uuid4()
    return NormalizedEvidence(evidence_id=eid,tenant_id=tenant,channel=channel,source_system='synthetic-benchmark',source_id=str(eid),source_key=f'synthetic:{eid}',title=title,content=content,content_hash=('a' if channel is EvidenceChannel.RUNTIME else 'b')*64,relevance_score=.95,source_confidence=.95,fusion_score=.95,locator=EvidenceLocator(timestamp=datetime(2026,8,17,14,minute,tzinfo=timezone.utc)),estimated_tokens=10,provenance={'service':'checkout','environment':'production'})

def proposal(cause, a, b, alt):
    return {'incident_summary':cause,'hypotheses':[
      {'hypothesis_id':'hyp-01','rank':1,'kind':'root_cause','statement':cause,'model_confidence':.92,'supporting_evidence_ids':[str(a.evidence_id),str(b.evidence_id)],'disconfirming_evidence_ids':[],'causal_links':[{'source_evidence_id':str(a.evidence_id),'target_evidence_id':str(b.evidence_id),'relation':'precedes','rationale':'evidence sequence supports the causal chain'}],'temporal_rationale':'supporting evidence aligns in the incident window','recommended_tests':[{'test_id':'test-01','objective':'Verify the implicated subsystem state','expected_if_true':'the failure signature remains observable','expected_if_false':'the subsystem is healthy','risk':'read_only'}]},
      {'hypothesis_id':'hyp-02','rank':2,'kind':'alternative','statement':alt,'model_confidence':.45,'supporting_evidence_ids':[str(b.evidence_id)],'disconfirming_evidence_ids':[],'causal_links':[],'temporal_rationale':'alternative is temporally plausible but less supported','recommended_tests':[]}], 'limitations':[]}

async def main():
    cases=[
      ('database connection pool exhaustion','checkout database pool saturated','requests waited for database connections','application thread contention'),
      ('incompatible database migration','schema change preceded query failures','runbook matches incompatible migration errors','database host saturation'),
      ('expired TLS certificate','certificate expiry event preceded handshake errors','logs show certificate validation failures','DNS resolution failure'),
      ('Redis memory saturation','Redis memory pressure preceded eviction spike','cache latency and evictions increased','upstream API latency'),
      ('Kafka consumer lag caused stale release state','consumer lag rose before stale-state alerts','runtime events show delayed release updates','PostgreSQL lock contention'),
    ]
    topk=3; correct=0; unsupported=0; rows=[]
    for cause,t1,t2,alt in cases:
        tenant=uuid4(); a=evidence(tenant,EvidenceChannel.RUNTIME,t1,t1,0); b=evidence(tenant,EvidenceChannel.TEXT,t2,t2,3)
        r=AgentRequest(tenant_id=tenant,user_id='benchmark',correlation_id='rca-benchmark',objective='Determine root cause',context={'service':'checkout','environment':'production'})
        auth=AgentAuthorization(tenant_id=tenant,user_id='benchmark',allowed_permissions=frozenset({ToolPermission.RCA_ANALYSIS_READ}))
        result=await RCAAgent(model=Model(proposal(cause,a,b,alt)),prompts=build_prompt_registry(),repository=InMemoryAgentRunRepository()).run(r,authorization=auth,evidence=[a,b])
        ranked=[x.statement for x in result.hypotheses[:topk]]
        hit=cause in ranked; correct += int(hit)
        unsupported += sum(1 for h in result.hypotheses if not h.supporting_evidence_ids)
        rows.append({'expected':cause,'top_k':ranked,'hit':hit,'determined':result.sufficiency.root_cause_determined})
    accuracy=correct/len(cases); unsupported_rate=unsupported/max(1,sum(len(r['top_k']) for r in rows))
    artifact={'cases':rows,'top_k':topk,'top_k_accuracy':accuracy,'unsupported_cause_rate':unsupported_rate,'threshold':0.8,'gate_passed':accuracy>=0.8 and unsupported_rate==0.0}
    Path('artifacts/rca-benchmark.json').write_text(json.dumps(artifact,indent=2)+'\n')
    print(json.dumps(artifact,indent=2))
    if not artifact['gate_passed']: raise SystemExit(1)
if __name__=='__main__': asyncio.run(main())
