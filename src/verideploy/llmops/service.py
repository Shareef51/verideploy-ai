from __future__ import annotations
import hashlib,json
from typing import Any
from uuid import UUID
from .schemas import CorrelationTrace,LLMOpsEvent,LLMOpsKind

_SECRET_KEYS={'authorization','api_key','access_token','refresh_token','password','secret','private_key','cookie','token'}
def redact_payload(value:Any)->Any:
    if isinstance(value,dict):
        return {k:('[REDACTED]' if k.lower() in _SECRET_KEYS or any(x in k.lower() for x in ('password','secret','token','api_key','private_key')) else redact_payload(v)) for k,v in value.items()}
    if isinstance(value,list): return [redact_payload(v) for v in value]
    return value

class LLMOpsService:
    def __init__(self,repository): self.repository=repository
    def record(self,event:LLMOpsEvent)->LLMOpsEvent:
        clean=event.model_copy(update={'payload':redact_payload(event.payload)})
        self.repository.append(clean); return clean
    def enforce_retention(self,*,tenant_id:UUID,before): return self.repository.purge_before(tenant_id=tenant_id,before=before)
    def trace(self,*,tenant_id:UUID,correlation_id:str)->CorrelationTrace:
        events=self.repository.list_by_correlation(tenant_id=tenant_id,correlation_id=correlation_id)
        events=sorted(events,key=lambda e:(e.occurred_at,str(e.event_id)))
        return CorrelationTrace(tenant_id=tenant_id,correlation_id=correlation_id,events=events,model_calls=sum(e.kind==LLMOpsKind.MODEL_CALL for e in events),tool_calls=sum(e.kind==LLMOpsKind.TOOL_CALL for e in events),retrieval_calls=sum(e.kind==LLMOpsKind.RETRIEVAL for e in events),retries=sum(e.retry_count for e in events),failures=sum(e.kind==LLMOpsKind.FAILURE or bool(e.failure_code) for e in events),input_tokens=sum(e.input_tokens for e in events),output_tokens=sum(e.output_tokens for e in events),total_tokens=sum(e.total_tokens for e in events),total_cost_usd=round(sum(e.cost_usd for e in events),8),total_latency_ms=round(sum(e.latency_ms for e in events),3),latest_confidence=next((e.confidence for e in reversed(events) if e.confidence is not None),None))
