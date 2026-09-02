from __future__ import annotations

from enum import StrEnum

from verideploy.exceptions import VeriDeployError


class AIErrorCode(StrEnum):
    CONFIGURATION = "configuration"
    AUTHENTICATION = "authentication"
    PERMISSION = "permission"
    INVALID_REQUEST = "invalid_request"
    RATE_LIMITED = "rate_limited"
    TIMEOUT = "timeout"
    CONNECTION = "connection"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    BUDGET_EXCEEDED = "budget_exceeded"
    LOCAL_RATE_LIMIT = "local_rate_limit"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


class AIProviderError(VeriDeployError):
    def __init__(
        self,
        message: str,
        *,
        code: AIErrorCode,
        retryable: bool,
        provider: str,
        status_code: int | None = None,
        provider_request_id: str | None = None,
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.provider = provider
        self.status_code = status_code
        self.provider_request_id = provider_request_id
        self.retry_after_seconds = retry_after_seconds
