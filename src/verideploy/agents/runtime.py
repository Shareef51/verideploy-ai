from __future__ import annotations

import statistics
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from verideploy.rag.fusion.schemas import RuntimeEvidenceInput, RuntimeEvidenceKind
from .base import BaseAgent
from .contracts import AgentAuthorization, AgentName, AgentRequest, ToolBudget, ToolPermission
from .runtime_tools import RuntimeSource, RuntimeToolPort, RuntimeToolQuery, RuntimeToolResult


class RuntimeSourcePlan(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    source: RuntimeSource
    query: str = Field(min_length=1, max_length=4000)

    @field_validator("source", mode="before")
    @classmethod
    def decode_source(cls, value): return RuntimeSource(value) if isinstance(value, str) else value


class RuntimeQueryAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    service: str = Field(min_length=1, max_length=120)
    environment: str = Field(min_length=1, max_length=80)
    window_start: datetime
    window_end: datetime
    baseline_minutes: int = Field(default=60, ge=5, le=10080)
    sources: list[RuntimeSourcePlan] = Field(min_length=1, max_length=4)
    rationale: str = Field(min_length=1, max_length=4000)

    @field_validator("window_start", "window_end", mode="before")
    @classmethod
    def decode_datetime(cls, value): return datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value

    @model_validator(mode="after")
    def normalize(self) -> "RuntimeQueryAnalysis":
        if self.window_start.tzinfo is None or self.window_end.tzinfo is None: raise ValueError("runtime analysis timestamps must be timezone-aware")
        self.window_start=self.window_start.astimezone(timezone.utc); self.window_end=self.window_end.astimezone(timezone.utc)
        if not self.window_start < self.window_end: raise ValueError("runtime analysis window_start must precede window_end")
        if (self.window_end-self.window_start)>timedelta(hours=24): raise ValueError("runtime analysis window exceeds 24 hours")
        if len({item.source for item in self.sources}) != len(self.sources): raise ValueError("duplicate runtime source")
        return self


class SourceStatus(StrEnum):
    OK="ok"; FAILED="failed"


class RuntimeSourceExecution(BaseModel):
    model_config=ConfigDict(extra="forbid")
    source: RuntimeSource
    status: SourceStatus
    query: str
    point_count: int=Field(ge=0)
    baseline_point_count: int=Field(ge=0)
    error_code: str|None=None


class RuntimeAnomaly(BaseModel):
    model_config=ConfigDict(extra="forbid")
    source: RuntimeSource
    title: str
    current_value: float
    baseline_value: float
    absolute_delta: float
    percent_change: float|None=None
    anomaly_score: float=Field(ge=0)
    anomalous: bool
    observed_at: datetime
    source_id: str


class RuntimeEvidenceSufficiency(BaseModel):
    model_config=ConfigDict(extra="forbid")
    sufficient: bool
    evidence_count: int=Field(ge=0)
    successful_sources: int=Field(ge=0)
    failed_sources: int=Field(ge=0)
    anomalous_sources: int=Field(ge=0)
    reason_codes: list[str]


class RuntimeEvidenceAgentResult(BaseModel):
    model_config=ConfigDict(extra="forbid")
    analysis: RuntimeQueryAnalysis
    evidence: list[RuntimeEvidenceInput]
    anomalies: list[RuntimeAnomaly]
    source_executions: list[RuntimeSourceExecution]
    sufficiency: RuntimeEvidenceSufficiency
    tool_calls_used: int=Field(ge=0,le=64)


class RuntimeEvidenceAgent(BaseAgent[RuntimeQueryAnalysis]):
    agent_name=AgentName.RUNTIME_EVIDENCE
    prompt_name="runtime_evidence"
    prompt_version="1.0.0"
    output_model=RuntimeQueryAnalysis
    schema_name="agent_runtime_query_analysis"

    def __init__(self, *, model, prompts, repository, tools: dict[RuntimeSource, RuntimeToolPort]) -> None:
        super().__init__(model=model,prompts=prompts,repository=repository); self.tools=tools

    async def run(self, request: AgentRequest, *, authorization: AgentAuthorization, budget: ToolBudget, min_evidence:int=1, min_successful_sources:int=1, anomaly_z_threshold:float=2.0, anomaly_percent_threshold:float=50.0) -> RuntimeEvidenceAgentResult:
        authorization.require([ToolPermission.RUNTIME_EVIDENCE_READ])
        analysis, run=await self._generate(request,authorization=authorization,budget=budget,payload={"objective":request.objective,"context":request.context,"allowed_sources":[s.value for s in RuntimeSource],"tool_budget":budget.max_calls,"max_window_hours":24})
        active=budget
        try:
            self._validate_scope(request,analysis)
            if len(analysis.sources)>active.remaining: raise RuntimeError("runtime evidence plan exceeds tool-call budget")
            baseline_end=analysis.window_start
            baseline_start=baseline_end-timedelta(minutes=analysis.baseline_minutes)
            evidence=[]; anomalies=[]; executions=[]
            for plan in analysis.sources:
                active=active.consume(); tool=self.tools.get(plan.source)
                if tool is None:
                    executions.append(RuntimeSourceExecution(source=plan.source,status=SourceStatus.FAILED,query=plan.query,point_count=0,baseline_point_count=0,error_code="RuntimeToolUnavailable")); continue
                try:
                    result=await tool.query(RuntimeToolQuery(tenant_id=request.tenant_id,source=plan.source,query=plan.query,service=analysis.service,environment=analysis.environment,start=analysis.window_start,end=analysis.window_end,baseline_start=baseline_start,baseline_end=baseline_end))
                    anomaly=self._anomaly(result, anomaly_z_threshold=anomaly_z_threshold, anomaly_percent_threshold=anomaly_percent_threshold)
                    if anomaly: anomalies.append(anomaly)
                    evidence.extend(self._evidence(request.tenant_id,analysis,result,anomaly))
                    executions.append(RuntimeSourceExecution(source=plan.source,status=SourceStatus.OK,query=plan.query,point_count=len(result.points),baseline_point_count=len(result.baseline_points)))
                except Exception as exc:
                    executions.append(RuntimeSourceExecution(source=plan.source,status=SourceStatus.FAILED,query=plan.query,point_count=0,baseline_point_count=0,error_code=type(exc).__name__))
            suff=self._sufficiency(evidence,executions,anomalies,min_evidence=min_evidence,min_successful_sources=min_successful_sources)
            result=RuntimeEvidenceAgentResult(analysis=analysis,evidence=evidence,anomalies=anomalies,source_executions=executions,sufficiency=suff,tool_calls_used=active.calls_used)
            self.repository.complete(tenant_id=request.tenant_id,run_id=run.run_id,output=result.model_dump(mode="json"),tool_calls_used=active.calls_used); return result
        except Exception as exc:
            self.repository.fail(tenant_id=request.tenant_id,run_id=run.run_id,error_code=type(exc).__name__,tool_calls_used=active.calls_used); raise

    @staticmethod
    def _validate_scope(request:AgentRequest, analysis:RuntimeQueryAnalysis)->None:
        for key,actual in (("service",analysis.service),("environment",analysis.environment)):
            trusted=request.context.get(key)
            if trusted is not None and actual!=trusted: raise PermissionError(f"runtime {key} cannot broaden trusted request scope")
        for key,actual in (("window_start",analysis.window_start),("window_end",analysis.window_end)):
            trusted=request.context.get(key)
            if trusted is not None:
                dt=datetime.fromisoformat(str(trusted).replace("Z","+00:00")).astimezone(timezone.utc)
                if actual!=dt: raise PermissionError(f"runtime {key} cannot change trusted request scope")

    @staticmethod
    def _anomaly(result:RuntimeToolResult, *, anomaly_z_threshold:float, anomaly_percent_threshold:float)->RuntimeAnomaly|None:
        if not result.points: return None
        current=[p.value for p in result.points]; baseline=[p.value for p in result.baseline_points]
        if result.source in {RuntimeSource.LOG, RuntimeSource.GRAFANA}:
            cur=float(len(result.points)); base=float(len(result.baseline_points))
        else:
            cur=statistics.fmean(current); base=statistics.fmean(baseline) if baseline else cur
        std=statistics.pstdev(baseline) if len(baseline)>1 else 0.0
        z=abs(cur-base)/std if std>0 else (abs(cur-base)/(abs(base) or 1.0))
        pct=((cur-base)/abs(base)*100.0) if base else None
        anomalous=z>=anomaly_z_threshold or (pct is not None and abs(pct)>=anomaly_percent_threshold)
        point=max(result.points,key=lambda p:p.observed_at)
        return RuntimeAnomaly(source=result.source,title=f"{result.source.value} runtime change",current_value=cur,baseline_value=base,absolute_delta=cur-base,percent_change=pct,anomaly_score=z,anomalous=anomalous,observed_at=point.observed_at,source_id=point.source_id)

    @staticmethod
    def _evidence(tenant_id:UUID, analysis:RuntimeQueryAnalysis, result:RuntimeToolResult, anomaly:RuntimeAnomaly|None)->list[RuntimeEvidenceInput]:
        if not result.points: return []
        kind={RuntimeSource.PROMETHEUS:RuntimeEvidenceKind.METRIC,RuntimeSource.LOG:RuntimeEvidenceKind.LOG,RuntimeSource.TRACE:RuntimeEvidenceKind.TRACE,RuntimeSource.GRAFANA:RuntimeEvidenceKind.EVENT}[result.source]
        point=max(result.points,key=lambda p:p.observed_at); score=min(1.0, 0.5+(0.1*(anomaly.anomaly_score if anomaly else 0)))
        content=point.text or f"{result.source.value} current={anomaly.current_value if anomaly else point.value:.4f} baseline={anomaly.baseline_value if anomaly else point.value:.4f}"
        eid=uuid5(NAMESPACE_URL,f"{tenant_id}:runtime:{result.source.value}:{point.source_id}:{point.observed_at.isoformat()}:{result.query}")
        return [RuntimeEvidenceInput(evidence_id=eid,tenant_id=tenant_id,kind=kind,source_system=result.source_system,source_id=point.source_id,title=f"{result.source.value}: {result.query[:160]}",content=content,relevance_score=score,source_confidence=1.0,observed_at=point.observed_at,service=analysis.service,environment=analysis.environment)]

    @staticmethod
    def _sufficiency(evidence, executions, anomalies, *, min_evidence:int, min_successful_sources:int)->RuntimeEvidenceSufficiency:
        ok=sum(1 for x in executions if x.status is SourceStatus.OK); failed=len(executions)-ok; reasons=[]
        if len(evidence)<min_evidence: reasons.append("insufficient_runtime_evidence")
        if ok<min_successful_sources: reasons.append("insufficient_runtime_sources")
        if failed: reasons.append("runtime_source_failure")
        return RuntimeEvidenceSufficiency(sufficient=not [r for r in reasons if r!="runtime_source_failure"] and bool(evidence),evidence_count=len(evidence),successful_sources=ok,failed_sources=failed,anomalous_sources=len({a.source for a in anomalies if a.anomalous}),reason_codes=reasons)
