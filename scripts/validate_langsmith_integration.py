from __future__ import annotations
import asyncio, json
from decimal import Decimal
from pathlib import Path
from uuid import uuid4
from verideploy.langsmith_integration.service import LangSmithObserver, LangSmithDatasetHook
from verideploy.llm.contracts import AIRequest
from verideploy.llm.controls import InMemoryRequestController, LocalControlPolicy
from verideploy.llm.gateway import AIGateway
from verideploy.llm.test_provider import DeterministicTestProvider

class Client:
    def __init__(self): self.created=[]; self.updated=[]; self.datasets=set(); self.examples=[]
    def create_run(self,**kw): self.created.append(kw)
    def update_run(self,run_id,**kw): self.updated.append((run_id,kw))
    def has_dataset(self,*,dataset_name): return dataset_name in self.datasets
    def create_dataset(self,*,dataset_name,description): self.datasets.add(dataset_name)
    def create_example(self,**kw): self.examples.append(kw)

async def main():
    client=Client(); obs=LangSmithObserver(client=client,environment='test',project_name='verideploy-test',dataset_export_enabled=True)
    req=AIRequest(tenant_id=uuid4(),correlation_id='validator',operation='validate.langsmith',model='test-model',input='synthetic input',metadata={'prompt_name':'validator','prompt_version':'1','prompt_sha256':'a'*64})
    ctrl=InMemoryRequestController(LocalControlPolicy(requests_per_minute=10,monthly_budget_usd=Decimal('10')))
    result=await AIGateway(provider=DeterministicTestProvider(output_text='business-result'),controller=ctrl,langsmith_observer=obs).execute(req)
    ds=LangSmithDatasetHook(client=client,enabled=True,environment='test',dataset_prefix='verideploy-evals')
    dataset_ok=ds.export_example(logical_dataset='validator',inputs={'api_key':'secret','input':'x'},outputs={'output':'y'})
    child=client.created[-1]
    checks={
      'business_result_preserved': result.output_text=='business-result',
      'root_and_child_created': len(client.created)==2,
      'hierarchy_parented': child.get('parent_run_id')==client.created[0].get('id'),
      'environment_project': child.get('project_name')=='verideploy-test',
      'correlation_metadata': child.get('extra',{}).get('metadata',{}).get('correlation_id')=='validator',
      'prompt_version_metadata': child.get('extra',{}).get('metadata',{}).get('prompt_version')=='1',
      'dataset_export_opt_in': dataset_ok,
      'dataset_environment_separated': 'verideploy-evals-test-validator' in client.datasets,
      'dataset_redacted': client.examples[-1]['inputs']['api_key']=='[REDACTED]',
    }
    payload={'valid':all(checks.values()),'checks':checks,'project':'verideploy-test','runs_created':len(client.created),'dataset_examples':len(client.examples)}
    Path('artifacts/langsmith-validation.json').write_text(json.dumps(payload,indent=2)+"\n")
    print(json.dumps(payload,indent=2))
    if not payload['valid']: raise SystemExit(1)
asyncio.run(main())
