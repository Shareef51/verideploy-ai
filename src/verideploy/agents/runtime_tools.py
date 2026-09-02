from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Protocol
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator


class RuntimeSource(StrEnum):
    PROMETHEUS = "prometheus"
    GRAFANA = "grafana"
    TRACE = "trace"
    LOG = "log"


class RuntimePoint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    observed_at: datetime
    value: float
    text: str | None = None
    source_id: str = Field(min_length=1, max_length=500)
    attributes: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def aware(self) -> "RuntimePoint":
        if self.observed_at.tzinfo is None:
            raise ValueError("runtime point timestamp must be timezone-aware")
        self.observed_at = self.observed_at.astimezone(timezone.utc)
        return self


class RuntimeToolQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenant_id: UUID
    source: RuntimeSource
    query: str = Field(min_length=1, max_length=4000)
    service: str = Field(min_length=1, max_length=120)
    environment: str = Field(min_length=1, max_length=80)
    start: datetime
    end: datetime
    baseline_start: datetime
    baseline_end: datetime
    limit: int = Field(default=200, ge=1, le=5000)

    @model_validator(mode="after")
    def normalize(self) -> "RuntimeToolQuery":
        values = [self.start, self.end, self.baseline_start, self.baseline_end]
        if any(item.tzinfo is None for item in values):
            raise ValueError("runtime query timestamps must be timezone-aware")
        self.start = self.start.astimezone(timezone.utc)
        self.end = self.end.astimezone(timezone.utc)
        self.baseline_start = self.baseline_start.astimezone(timezone.utc)
        self.baseline_end = self.baseline_end.astimezone(timezone.utc)
        if not self.start < self.end:
            raise ValueError("runtime query start must precede end")
        if not self.baseline_start < self.baseline_end or self.baseline_end > self.start:
            raise ValueError("baseline window must be complete and not overlap the active window")
        return self


class RuntimeToolResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: RuntimeSource
    source_system: str
    query: str
    points: list[RuntimePoint]
    baseline_points: list[RuntimePoint]
    metadata: dict[str, Any] = Field(default_factory=dict)


class RuntimeToolPort(Protocol):
    async def query(self, request: RuntimeToolQuery) -> RuntimeToolResult: ...


class SyntheticRuntimeTool:
    """Deterministic CI/demo source. Never claims to be live telemetry."""

    def __init__(self, source: RuntimeSource) -> None:
        self.source = source
        self.calls: list[RuntimeToolQuery] = []

    async def query(self, request: RuntimeToolQuery) -> RuntimeToolResult:
        if request.source != self.source:
            raise ValueError("runtime source mismatch")
        self.calls.append(request)
        span = max((request.end - request.start).total_seconds(), 1)
        seed = sum(ord(ch) for ch in f"{request.service}:{request.environment}:{request.query}:{request.source.value}")
        baseline = 10.0 + (seed % 11)
        anomaly = baseline * (1.0 + ((seed % 7) + 4) / 10.0)
        if request.source is RuntimeSource.LOG:
            baseline, anomaly = max(1.0, baseline // 2), max(3.0, anomaly)
        points = [RuntimePoint(observed_at=request.end, value=anomaly, text=f"synthetic {request.source.value} signal for {request.service}", source_id=f"synthetic:{request.source.value}:{seed}", attributes={"service.name": request.service, "deployment.environment.name": request.environment})]
        base_points = [RuntimePoint(observed_at=request.baseline_end, value=baseline, source_id=f"synthetic:{request.source.value}:baseline:{seed}", attributes={"service.name": request.service, "deployment.environment.name": request.environment})]
        return RuntimeToolResult(source=request.source, source_system=f"synthetic-{request.source.value}", query=request.query, points=points, baseline_points=base_points, metadata={"synthetic": True, "window_seconds": span})


@dataclass(frozen=True)
class LiveRuntimeEndpoints:
    prometheus_url: str | None = None
    grafana_url: str | None = None
    tempo_url: str | None = None
    loki_url: str | None = None
    bearer_token: str | None = None


class LiveRuntimeTool:
    """Read-only HTTP adapters for Prometheus, Grafana annotations, Tempo search and Loki."""

    def __init__(self, source: RuntimeSource, endpoints: LiveRuntimeEndpoints, *, timeout_seconds: float = 15.0, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.source = source
        self.endpoints = endpoints
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    async def query(self, request: RuntimeToolQuery) -> RuntimeToolResult:
        if request.source != self.source:
            raise ValueError("runtime source mismatch")
        self._validate_scope(request)
        headers = {"Authorization": f"Bearer {self.endpoints.bearer_token}"} if self.endpoints.bearer_token else {}
        async with httpx.AsyncClient(timeout=self.timeout_seconds, headers=headers, transport=self.transport) as client:
            if self.source is RuntimeSource.PROMETHEUS:
                return await self._prometheus(client, request)
            if self.source is RuntimeSource.LOG:
                return await self._loki(client, request)
            if self.source is RuntimeSource.GRAFANA:
                return await self._grafana(client, request)
            return await self._tempo(client, request)


    def _validate_scope(self, request: RuntimeToolQuery) -> None:
        if self.source is RuntimeSource.GRAFANA:
            return
        query = request.query
        values = (request.service, request.environment)
        if any(re.search(rf'([=!~]\s*)?["\']?{re.escape(value)}["\']?', query, re.IGNORECASE) is None for value in values):
            raise PermissionError("live runtime query must explicitly include trusted service and environment scope")

    @staticmethod
    def _ts(dt: datetime) -> str:
        return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    async def _prometheus(self, client: httpx.AsyncClient, request: RuntimeToolQuery) -> RuntimeToolResult:
        if not self.endpoints.prometheus_url:
            raise RuntimeError("Prometheus endpoint is not configured")
        async def fetch(start: datetime, end: datetime) -> list[RuntimePoint]:
            duration = max((end - start).total_seconds(), 1)
            step = max(1, int(duration / 120))
            r = await client.get(self.endpoints.prometheus_url.rstrip("/") + "/api/v1/query_range", params={"query": request.query, "start": self._ts(start), "end": self._ts(end), "step": step})
            r.raise_for_status(); payload = r.json()
            if payload.get("status") != "success": raise RuntimeError("Prometheus query failed")
            points: list[RuntimePoint] = []
            for series in payload.get("data", {}).get("result", []):
                labels = {str(k): str(v) for k, v in series.get("metric", {}).items()}
                for ts, value in series.get("values", []):
                    try: numeric = float(value)
                    except (TypeError, ValueError): continue
                    if math.isfinite(numeric): points.append(RuntimePoint(observed_at=datetime.fromtimestamp(float(ts), tz=timezone.utc), value=numeric, source_id=str(labels), attributes=labels))
            return points[: request.limit]
        return RuntimeToolResult(source=self.source, source_system="prometheus", query=request.query, points=await fetch(request.start, request.end), baseline_points=await fetch(request.baseline_start, request.baseline_end))

    async def _loki(self, client: httpx.AsyncClient, request: RuntimeToolQuery) -> RuntimeToolResult:
        if not self.endpoints.loki_url:
            raise RuntimeError("Loki endpoint is not configured")
        async def fetch(start: datetime, end: datetime) -> list[RuntimePoint]:
            r = await client.get(self.endpoints.loki_url.rstrip("/") + "/loki/api/v1/query_range", params={"query": request.query, "start": str(int(start.timestamp()*1_000_000_000)), "end": str(int(end.timestamp()*1_000_000_000)), "limit": request.limit, "direction": "forward"})
            r.raise_for_status(); payload=r.json(); points=[]
            for stream in payload.get("data", {}).get("result", []):
                labels={str(k):str(v) for k,v in stream.get("stream",{}).items()}
                for ns, line in stream.get("values", []):
                    points.append(RuntimePoint(observed_at=datetime.fromtimestamp(int(ns)/1_000_000_000,tz=timezone.utc), value=1.0, text=str(line)[:10000], source_id=str(labels), attributes=labels))
            return points[:request.limit]
        return RuntimeToolResult(source=self.source, source_system="loki", query=request.query, points=await fetch(request.start,request.end), baseline_points=await fetch(request.baseline_start,request.baseline_end))

    async def _grafana(self, client: httpx.AsyncClient, request: RuntimeToolQuery) -> RuntimeToolResult:
        if not self.endpoints.grafana_url:
            raise RuntimeError("Grafana endpoint is not configured")
        async def fetch(start: datetime, end: datetime) -> list[RuntimePoint]:
            params: list[tuple[str,str|int]]=[("from",int(start.timestamp()*1000)),("to",int(end.timestamp()*1000)),("limit",request.limit)]
            params.extend(("tags", tag.strip()) for tag in request.query.split(",") if tag.strip())
            params.extend([("tags", f"service:{request.service}"), ("tags", f"environment:{request.environment}")])
            r=await client.get(self.endpoints.grafana_url.rstrip("/")+"/api/annotations",params=params); r.raise_for_status(); points=[]
            for item in r.json():
                millis=item.get("time") or item.get("timeEnd")
                if millis is None: continue
                points.append(RuntimePoint(observed_at=datetime.fromtimestamp(float(millis)/1000,tz=timezone.utc),value=1.0,text=str(item.get("text") or "")[:10000],source_id=str(item.get("id") or item.get("uid") or millis),attributes={"dashboardUID":str(item.get("dashboardUID") or ""),"panelId":str(item.get("panelId") or "")}))
            return points
        return RuntimeToolResult(source=self.source,source_system="grafana-annotations",query=request.query,points=await fetch(request.start,request.end),baseline_points=await fetch(request.baseline_start,request.baseline_end))

    async def _tempo(self, client: httpx.AsyncClient, request: RuntimeToolQuery) -> RuntimeToolResult:
        if not self.endpoints.tempo_url:
            raise RuntimeError("Tempo endpoint is not configured")
        async def fetch(start: datetime, end: datetime) -> list[RuntimePoint]:
            params={"q":request.query,"start":int(start.timestamp()),"end":int(end.timestamp()),"limit":request.limit}
            r=await client.get(self.endpoints.tempo_url.rstrip("/")+"/api/search",params=params); r.raise_for_status(); payload=r.json(); points=[]
            for trace in payload.get("traces",[]):
                start_ns=trace.get("startTimeUnixNano") or trace.get("startTimeUnixNanos")
                duration_ms=float(trace.get("durationMs") or 0.0)
                if start_ns is None: continue
                points.append(RuntimePoint(observed_at=datetime.fromtimestamp(int(start_ns)/1_000_000_000,tz=timezone.utc),value=duration_ms,text=str(trace.get("rootTraceName") or trace.get("rootServiceName") or "trace"),source_id=str(trace.get("traceID") or trace.get("traceId") or start_ns),attributes={"service.name":str(trace.get("rootServiceName") or request.service)}))
            return points
        return RuntimeToolResult(source=self.source,source_system="tempo",query=request.query,points=await fetch(request.start,request.end),baseline_points=await fetch(request.baseline_start,request.baseline_end))
