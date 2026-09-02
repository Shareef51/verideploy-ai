from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import ValidationError


class FailureClass(StrEnum):
    TRANSIENT = "transient"
    LLM_RECOVERABLE = "llm_recoverable"
    USER_FIXABLE = "user_fixable"
    AUTHORIZATION = "authorization"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    PROMPT_INJECTION = "prompt_injection"
    CRITIC_FAILURE = "critic_failure"
    FATAL = "fatal"
    UNKNOWN = "unknown"


class GraphBudgetExceeded(RuntimeError):
    pass


def _status(exc: Exception) -> int | None:
    value=getattr(exc,"status_code",None) or getattr(getattr(exc,"response",None),"status_code",None)
    return value if isinstance(value,int) else None


def classify_failure(exc: Exception, *, node_name: str | None=None) -> FailureClass:
    name=type(exc).__name__; message=str(exc).casefold(); status=_status(exc)
    code=str(getattr(exc,"code","")).casefold()
    if isinstance(exc,GraphBudgetExceeded): return FailureClass.FATAL
    if isinstance(exc,PermissionError) or status in {401,403}: return FailureClass.AUTHORIZATION
    if code in {"authentication","permission","integration_host_denied"}: return FailureClass.AUTHORIZATION
    if "prompt injection" in message or "promptinjection" in name.casefold(): return FailureClass.PROMPT_INJECTION
    if isinstance(exc,ValidationError): return FailureClass.USER_FIXABLE
    if name in {"StructuredOutputValidationError","UnknownStructuredSchemaError"} or "schema" in message: return FailureClass.LLM_RECOVERABLE
    if "insufficient" in message and "evidence" in message: return FailureClass.INSUFFICIENT_EVIDENCE
    if getattr(exc,"retryable",False) is True or code in {"rate_limited","timeout","connection","provider_unavailable"} or isinstance(exc,(TimeoutError,ConnectionError)) or name in {"APIConnectionError","APITimeoutError","RateLimitError","OperationalError","DBAPIError"} or status in {408,409,425,429} or (status is not None and status>=500): return FailureClass.TRANSIENT
    if node_name=="critic": return FailureClass.CRITIC_FAILURE
    if status in {400,404,422} or code in {"invalid_request","integration_unconfigured"} or isinstance(exc,(ValueError,KeyError)): return FailureClass.USER_FIXABLE
    if isinstance(exc,(MemoryError,SystemExit,KeyboardInterrupt)): return FailureClass.FATAL
    return FailureClass.UNKNOWN


def retry_transient(exc: Exception) -> bool:
    return classify_failure(exc) is FailureClass.TRANSIENT


def error_state(node_name: str, exc: Exception) -> dict[str, Any]:
    category=classify_failure(exc,node_name=node_name)
    return {"node":node_name,"category":category.value,"error_type":type(exc).__name__,"message":str(exc)[:1000],"retryable":category is FailureClass.TRANSIENT}
