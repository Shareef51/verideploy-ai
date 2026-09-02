from __future__ import annotations
import asyncio, json
from datetime import datetime, timezone
from uuid import uuid4

from verideploy.agents.contracts import AgentAuthorization, AgentRequest, ToolBudget, ToolPermission
from verideploy.agents.critic import CriticAgent
from verideploy.agents.prompts import build_prompt_registry
from verideploy.agents.rca import RCAAgentResult, RCAHypothesisAssessment, RCAHypothesisKind, RCASufficiency
from verideploy.agents.repository import InMemoryAgentRunRepository
from verideploy.rag.fusion.schemas import EvidenceChannel, EvidenceLocator, NormalizedEvidence

class Dummy: pass

def evidence(tenant, content, channel=EvidenceChannel.RUNTIME):
    eid=uuid4()
    return NormalizedEvidence(evidence_id=eid,tenant_id=tenant,channel=channel,source_system='benchmark',source_id=str(eid),source_key=str(eid),title='benchmark',content=content,content_hash=('a' if channel is EvidenceChannel.RUNTIME else 'b')*64,relevance_score=.95,source_confidence=.95,fusion_score=.95,locator=EvidenceLocator(timestamp=datetime(2026,8,17,14,0,tzinfo=timezone.utc)),estimated_tokens=20,provenance={'service':'checkout','environment':'production'})

def rca(a,b,statement,disconfirm=None):
    h=RCAHypothesisAssessment(hypothesis_id='hyp-01',rank=1,kind=RCAHypothesisKind.ROOT_CAUSE,statement=statement,model_confidence=.95,adjusted_confidence=.9,support_count=2,contradiction_count=1 if disconfirm else 0,supporting_channels=sorted({a.channel,b.channel},key=lambda x:x.value),temporal_score=1,causal_score=1,supporting_evidence_ids=[a.evidence_id,b.evidence_id],disconfirming_evidence_ids=[disconfirm.evidence_id] if disconfirm else [],causal_links=[],temporal_rationale='aligned',recommended_tests=[])
    return RCAAgentResult(incident_summary='benchmark incident',hypotheses=[h],root_causes=[h],triggers=[],alternatives=[],limitations=[],sufficiency=RCASufficiency(root_cause_determined=True,top_hypothesis_id='hyp-01',evidence_count=2+(1 if disconfirm else 0),evidence_channels=h.supporting_channels,reason_codes=['sufficient']),tool_calls_used=0)

async def main():
    tenant=uuid4(); request=AgentRequest(tenant_id=tenant,user_id='benchmark',correlation_id='critic-benchmark',objective='Critique RCA',context={'service':'checkout','environment':'production'})
    auth=AgentAuthorization(tenant_id=tenant,user_id='benchmark',allowed_permissions=frozenset({ToolPermission.CRITIC_ANALYSIS_READ}))
    agent=CriticAgent(model=Dummy(),prompts=build_prompt_registry(),repository=InMemoryAgentRunRepository())
    a=evidence(tenant,'database connection pool reached maximum and exhausted available connections')
    b=evidence(tenant,'connection pool exhaustion causes checkout latency and queueing',EvidenceChannel.TEXT)
    d=evidence(tenant,'database connection pool remained healthy and below 40 percent')
    cases=[
        ('supported',rca(a,b,'Database connection pool exhaustion caused checkout latency'),[a,b],True),
        ('hallucinated',rca(a,b,'Kernel memory corruption caused checkout latency'),[a,b],False),
        ('contradictory',rca(a,b,'Database connection pool exhaustion caused checkout latency',d),[a,b,d],False),
    ]
    results=[]
    for name, report, evs, expected in cases:
        out=await agent.run(request,authorization=auth,rca=report,evidence=evs,budget=ToolBudget(max_calls=0),max_followups=0,model_name='benchmark',dimensions=3,candidate_k=4)
        results.append({'case':name,'passed':out.passed,'expected_pass':expected,'hallucinated':out.hallucinated_claim_count,'contradicted':out.contradicted_claim_count,'gate_ok':out.passed==expected})
    payload={'cases':results,'bad_rca_rejection_rate':sum((not x['passed']) for x in results[1:])/2,'gate_passed':all(x['gate_ok'] for x in results)}
    print(json.dumps(payload,indent=2,sort_keys=True))
    raise SystemExit(0 if payload['gate_passed'] else 1)

if __name__=='__main__': asyncio.run(main())
