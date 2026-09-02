from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Iterable

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode


class GuardrailLayer(StrEnum):
    INPUT = "input"
    RETRIEVAL = "retrieval"
    TOOL = "tool"
    OUTPUT = "output"
    OPERATIONAL = "operational"


class GuardrailAction(StrEnum):
    ALLOW = "allow"
    WARN = "warn"
    DENY = "deny"
    ABSTAIN = "abstain"


@dataclass(frozen=True)
class GuardrailContext:
    tenant_id: str
    actor_id: str = "anonymous"
    role: str = "viewer"
    correlation_id: str = "unknown"
    trace_id: str | None = None
    span_id: str | None = None
    channel: str = "http"
    environment: str = "unknown"


@dataclass(frozen=True)
class GuardrailViolation:
    layer: GuardrailLayer
    control_id: str
    action: GuardrailAction
    reason: str
    policy_version: str
    correlation_id: str
    trace_id: str | None
    span_id: str | None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GuardrailDecision:
    action: GuardrailAction
    violations: tuple[GuardrailViolation, ...] = ()
    sanitized: Any = None

    @property
    def allowed(self) -> bool:
        return self.action in {GuardrailAction.ALLOW, GuardrailAction.WARN}


class GuardrailDenied(PermissionError):
    def __init__(self, decision: GuardrailDecision):
        self.decision = decision
        controls = ", ".join(v.control_id for v in decision.violations)
        super().__init__(f"request blocked by guardrails ({controls})")


class GuardrailTelemetry:
    """Thread-safe in-process telemetry sink; OTel span events are emitted too."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._events: deque[GuardrailViolation] = deque(maxlen=10_000)
        self._counts: dict[tuple[str, str, str], int] = defaultdict(int)

    def record(self, violation: GuardrailViolation) -> None:
        with self._lock:
            self._events.append(violation)
            self._counts[(violation.layer.value, violation.control_id, violation.action.value)] += 1
        span = trace.get_current_span()
        if span.is_recording():
            span.add_event("guardrail.violation", {
                "guardrail.layer": violation.layer.value,
                "guardrail.control_id": violation.control_id,
                "guardrail.action": violation.action.value,
                "guardrail.policy_version": violation.policy_version,
                "correlation.id": violation.correlation_id,
            })
            if violation.action in {GuardrailAction.DENY, GuardrailAction.ABSTAIN}:
                span.set_status(Status(StatusCode.ERROR, "guardrail_block"))

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "counts": {"|".join(k): v for k, v in sorted(self._counts.items())},
                "recent": [v.__dict__ | {"layer": v.layer.value, "action": v.action.value} for v in list(self._events)[-100:]],
            }


class GuardrailPolicy:
    def __init__(self, raw: dict[str, Any], *, source: str = "inline") -> None:
        self.raw = raw
        self.source = source
        self.version = str(raw.get("version", "0"))
        canonical = json.dumps(raw, sort_keys=True, separators=(",", ":")).encode()
        self.sha256 = hashlib.sha256(canonical).hexdigest()

    @classmethod
    def load(cls, path: str | Path) -> "GuardrailPolicy":
        p = Path(path)
        return cls(json.loads(p.read_text(encoding="utf-8")), source=str(p))

    def section(self, name: str) -> dict[str, Any]:
        value = self.raw.get(name, {})
        return value if isinstance(value, dict) else {}


_SECRET_KEY = re.compile(r"(authorization|api[_-]?key|token|secret|password|cookie)", re.I)
_INJECTION = [
    re.compile(r"ignore\s+(all\s+)?previous\s+instructions", re.I),
    re.compile(r"(reveal|print|return).{0,30}(system prompt|developer message|api key|secret|credentials)", re.I),
    re.compile(r"(disable|bypass|override).{0,20}(guardrail|security|authorization|policy)", re.I),
    re.compile(r"execute.{0,30}(without|skip).{0,20}(approval|authorization)", re.I),
    re.compile(r"<\s*(system|assistant|developer)\s*>", re.I),
    re.compile(r"BEGIN\s+(SYSTEM|DEVELOPER)\s+PROMPT", re.I),
]
_UNSAFE_ACTION = re.compile(r"\b(delete|drop|destroy|rollback|deploy|terminate|revoke|rotate)\b", re.I)
_PII = re.compile(r"\b(?:\d[ -]*?){13,19}\b|\b\d{3}-\d{2}-\d{4}\b")
_CITATION = re.compile(r"\[(?:evidence|source|trace|doc):[^\]]+\]", re.I)


def _walk_strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for k, v in value.items():
            yield str(k)
            yield from _walk_strings(v)
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            yield from _walk_strings(item)


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: "[REDACTED]" if _SECRET_KEY.search(str(k)) else _redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v) for v in value]
    if isinstance(value, str):
        value = _PII.sub("[REDACTED]", value)
        return value[:20_000]
    return value


class GuardrailEngine:
    def __init__(self, policy: GuardrailPolicy, telemetry: GuardrailTelemetry | None = None) -> None:
        self.policy = policy
        self.telemetry = telemetry or GuardrailTelemetry()
        self._rate: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _v(self, layer: GuardrailLayer, control: str, action: GuardrailAction, reason: str, ctx: GuardrailContext, **metadata: Any) -> GuardrailViolation:
        v = GuardrailViolation(layer, control, action, reason, self.policy.version, ctx.correlation_id, ctx.trace_id, ctx.span_id, metadata)
        self.telemetry.record(v)
        return v

    @staticmethod
    def _final(violations: list[GuardrailViolation], sanitized: Any = None) -> GuardrailDecision:
        if any(v.action is GuardrailAction.DENY for v in violations): action = GuardrailAction.DENY
        elif any(v.action is GuardrailAction.ABSTAIN for v in violations): action = GuardrailAction.ABSTAIN
        elif violations: action = GuardrailAction.WARN
        else: action = GuardrailAction.ALLOW
        return GuardrailDecision(action, tuple(violations), sanitized)

    def enforce(self, decision: GuardrailDecision) -> GuardrailDecision:
        if not decision.allowed:
            raise GuardrailDenied(decision)
        return decision

    def check_input(self, payload: Any, ctx: GuardrailContext) -> GuardrailDecision:
        cfg = self.policy.section("input")
        violations: list[GuardrailViolation] = []
        encoded = json.dumps(payload, default=str)
        if len(encoded.encode()) > int(cfg.get("max_bytes", 1_000_000)):
            violations.append(self._v(GuardrailLayer.INPUT, "INP-001", GuardrailAction.DENY, "payload exceeds configured size", ctx))
        if any(p.search(s) for s in _walk_strings(payload) for p in _INJECTION):
            violations.append(self._v(GuardrailLayer.INPUT, "INP-002", GuardrailAction.DENY, "prompt injection pattern detected", ctx, channel=ctx.channel))
        supplied_tenant = payload.get("tenant_id") if isinstance(payload, dict) else None
        if supplied_tenant is not None and str(supplied_tenant) != ctx.tenant_id:
            violations.append(self._v(GuardrailLayer.INPUT, "INP-003", GuardrailAction.DENY, "tenant mismatch", ctx))
        return self._final(violations, _redact(payload))

    def check_retrieval(self, chunks: list[dict[str, Any]], ctx: GuardrailContext) -> GuardrailDecision:
        violations: list[GuardrailViolation] = []
        sanitized: list[dict[str, Any]] = []
        for chunk in chunks:
            tenant = str(chunk.get("tenant_id", ""))
            if tenant and tenant != ctx.tenant_id:
                violations.append(self._v(GuardrailLayer.RETRIEVAL, "RET-001", GuardrailAction.DENY, "cross-tenant retrieval result", ctx, evidence_id=chunk.get("evidence_id")))
                continue
            text = str(chunk.get("text", ""))
            poisoned = any(p.search(text) for p in _INJECTION)
            copy = dict(chunk)
            if poisoned:
                violations.append(self._v(GuardrailLayer.RETRIEVAL, "RET-002", GuardrailAction.WARN, "instruction-like retrieved content quarantined", ctx, evidence_id=chunk.get("evidence_id")))
                copy["untrusted_instruction_detected"] = True
                copy["text"] = "[QUARANTINED_UNTRUSTED_INSTRUCTION]"
            sanitized.append(_redact(copy))
        return self._final(violations, sanitized)

    def check_tool(self, tool_name: str, arguments: dict[str, Any], ctx: GuardrailContext, *, risk: str = "read", approved: bool = False, dry_run: bool = True) -> GuardrailDecision:
        cfg = self.policy.section("tool")
        violations: list[GuardrailViolation] = []
        allowed_roles = cfg.get("allowed_roles", {}).get(tool_name)
        if allowed_roles and ctx.role not in allowed_roles:
            violations.append(self._v(GuardrailLayer.TOOL, "TOL-001", GuardrailAction.DENY, "role not authorized for tool", ctx, tool=tool_name, role=ctx.role))
        inp = self.check_input(arguments, ctx)
        for v in inp.violations:
            violations.append(self._v(GuardrailLayer.TOOL, "TOL-002", v.action, v.reason, ctx, tool=tool_name, source_control=v.control_id))
        tenant = arguments.get("tenant_id")
        if tenant is not None and str(tenant) != ctx.tenant_id:
            violations.append(self._v(GuardrailLayer.TOOL, "TOL-003", GuardrailAction.DENY, "tool tenant mismatch", ctx, tool=tool_name))
        consequential = risk in {"write", "high", "critical"} or bool(_UNSAFE_ACTION.search(tool_name))
        if consequential and not dry_run:
            violations.append(self._v(GuardrailLayer.TOOL, "TOL-004", GuardrailAction.DENY, "consequential action must start in dry-run", ctx, tool=tool_name))
        if consequential and not approved:
            violations.append(self._v(GuardrailLayer.TOOL, "TOL-005", GuardrailAction.DENY, "human approval required", ctx, tool=tool_name))
        scoped = dict(_redact(arguments)); scoped["tenant_id"] = ctx.tenant_id
        return self._final(violations, scoped)

    def check_output(self, output: Any, ctx: GuardrailContext, *, claims: list[dict[str, Any]] | None = None) -> GuardrailDecision:
        violations: list[GuardrailViolation] = []
        claims = claims or []
        for claim in claims:
            material = bool(claim.get("material", True))
            supported = bool(claim.get("supported", False))
            citation = str(claim.get("citation", ""))
            if material and not supported:
                violations.append(self._v(GuardrailLayer.OUTPUT, "OUT-001", GuardrailAction.ABSTAIN, "unsupported material claim", ctx, claim_id=claim.get("id")))
            if material and supported and not _CITATION.search(citation):
                violations.append(self._v(GuardrailLayer.OUTPUT, "OUT-002", GuardrailAction.ABSTAIN, "material claim missing stable citation", ctx, claim_id=claim.get("id")))
        return self._final(violations, _redact(output))

    def check_operational(self, operation: str, ctx: GuardrailContext, *, estimated_cost_usd: float = 0.0, retries: int = 0, concurrency: int = 1) -> GuardrailDecision:
        cfg = self.policy.section("operational")
        violations: list[GuardrailViolation] = []
        if retries > int(cfg.get("max_retries", 3)):
            violations.append(self._v(GuardrailLayer.OPERATIONAL, "OPS-001", GuardrailAction.DENY, "retry ceiling exceeded", ctx, operation=operation, retries=retries))
        if estimated_cost_usd > float(cfg.get("max_request_cost_usd", 5.0)):
            violations.append(self._v(GuardrailLayer.OPERATIONAL, "OPS-002", GuardrailAction.DENY, "request cost budget exceeded", ctx, operation=operation))
        if concurrency > int(cfg.get("max_concurrency", 32)):
            violations.append(self._v(GuardrailLayer.OPERATIONAL, "OPS-003", GuardrailAction.DENY, "concurrency ceiling exceeded", ctx, operation=operation))
        rpm = int(cfg.get("requests_per_minute", 120))
        now = time.monotonic(); key = f"{ctx.tenant_id}:{operation}"
        with self._lock:
            q = self._rate[key]
            while q and now - q[0] >= 60: q.popleft()
            if len(q) >= rpm:
                violations.append(self._v(GuardrailLayer.OPERATIONAL, "OPS-004", GuardrailAction.DENY, "rate limit exceeded", ctx, operation=operation))
            else: q.append(now)
        return self._final(violations)


def default_engine(path: str | Path = "config/guardrails/policy.json") -> GuardrailEngine:
    return GuardrailEngine(GuardrailPolicy.load(path))
