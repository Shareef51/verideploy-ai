from __future__ import annotations
from decimal import Decimal
from typing import Protocol
from typing import Any
from verideploy.llmops.schemas import LLMOpsEvent,LLMOpsKind
from verideploy.llmops.service import LLMOpsService

class ModelCallSink(Protocol):
    async def success(self,*,request:Any,result:Any,latency_ms:float)->None: ...
    async def failure(self,*,request:Any,model:str,role:str,retry_count:int,latency_ms:float,error_code:str)->None: ...

class LLMOpsModelCallSink:
    def __init__(self,service:LLMOpsService): self.service=service
    async def success(self,*,request,result,latency_ms):
        md=request.metadata or {}; u=result.usage
        self.service.record(LLMOpsEvent(tenant_id=request.tenant_id,correlation_id=request.correlation_id,kind=LLMOpsKind.MODEL_CALL,operation=request.operation,prompt_name=md.get('prompt_name'),prompt_version=md.get('prompt_version'),prompt_sha256=md.get('prompt_sha256'),model_role=result.model_role.value if result.model_role else None,model_name=result.model,input_tokens=u.input_tokens or 0,output_tokens=u.output_tokens or 0,total_tokens=u.total_tokens or ((u.input_tokens or 0)+(u.output_tokens or 0)),latency_ms=latency_ms,cost_usd=float(result.actual_cost_usd or result.estimated_cost_usd or 0),retry_count=max(0,result.attempts-1),payload={'provider':result.provider.value,'route_reason':result.route_reason,'fallback_index':result.fallback_index,'provider_response_id':result.provider_response_id}))
    async def failure(self,*,request,model,role,retry_count,latency_ms,error_code):
        md=request.metadata or {}; self.service.record(LLMOpsEvent(tenant_id=request.tenant_id,correlation_id=request.correlation_id,kind=LLMOpsKind.FAILURE,operation=request.operation,prompt_name=md.get('prompt_name'),prompt_version=md.get('prompt_version'),prompt_sha256=md.get('prompt_sha256'),model_role=role,model_name=model,latency_ms=latency_ms,retry_count=retry_count,failure_code=error_code))
