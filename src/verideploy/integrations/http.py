from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import httpx

from .errors import (
    IntegrationHostDenied,
    IntegrationQuotaExceeded,
    IntegrationRequestFailed,
    IntegrationUnconfigured,
)


@dataclass
class RequestBudget:
    max_requests: int
    requests_made: int = 0

    def consume(self) -> None:
        if self.requests_made >= self.max_requests:
            raise IntegrationQuotaExceeded("integration request quota exhausted")
        self.requests_made += 1


@dataclass(frozen=True)
class HTTPIntegrationPolicy:
    max_attempts: int = 3
    max_requests: int = 20
    timeout_seconds: float = 15.0
    backoff_base_seconds: float = 0.25
    max_retry_delay_seconds: float = 60.0


class ResilientReadClient:
    """Read-only HTTP client with explicit host, retry, redirect and per-run quota policy."""

    def __init__(
        self,
        *,
        base_url: str | None,
        allowed_hosts: set[str],
        headers: dict[str, str] | None = None,
        policy: HTTPIntegrationPolicy | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = (base_url or "").rstrip("/")
        self.allowed_hosts = {h.lower() for h in allowed_hosts if h}
        self.headers = dict(headers or {})
        self.policy = policy or HTTPIntegrationPolicy()
        self.transport = transport
        self.total_requests_made = 0
        if self.base_url:
            self._validate_url(self.base_url)

    @property
    def configured(self) -> bool:
        return bool(self.base_url)

    def _validate_url(self, url: str) -> None:
        parsed = urlparse(url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.hostname.lower() not in self.allowed_hosts
            or parsed.username
            or parsed.password
        ):
            raise IntegrationHostDenied("integration host is not allowlisted")

    def _url(self, path_or_url: str) -> str:
        url = path_or_url if path_or_url.startswith(("http://", "https://")) else self.base_url + path_or_url
        self._validate_url(url)
        return url

    def new_budget(self) -> RequestBudget:
        return RequestBudget(max_requests=self.policy.max_requests)

    async def request(
        self,
        method: str,
        path_or_url: str,
        *,
        budget: RequestBudget | None = None,
        **kwargs,
    ) -> httpx.Response:
        if method.upper() != "GET":
            raise IntegrationRequestFailed("integration client is read-only")
        if not self.configured:
            raise IntegrationUnconfigured("integration endpoint is not configured")
        url = self._url(path_or_url)
        budget = budget or self.new_budget()
        last: Exception | None = None

        for attempt in range(1, self.policy.max_attempts + 1):
            budget.consume()
            self.total_requests_made += 1
            try:
                async with httpx.AsyncClient(
                    timeout=self.policy.timeout_seconds,
                    headers=self.headers,
                    transport=self.transport,
                    follow_redirects=False,
                ) as client:
                    response = await client.get(url, **kwargs)
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last = exc
                if attempt >= self.policy.max_attempts:
                    break
                await asyncio.sleep(self._exponential_delay(attempt))
                continue

            if response.is_redirect:
                location = response.headers.get("location")
                if not location:
                    raise IntegrationRequestFailed("redirect missing location")
                url = urljoin(url, location)
                self._validate_url(url)
                if attempt >= self.policy.max_attempts:
                    raise IntegrationRequestFailed("redirect limit exhausted")
                continue

            if response.status_code < 400:
                return response

            if not self._is_retryable(response):
                raise IntegrationRequestFailed(f"non-retryable provider response {response.status_code}")

            if attempt >= self.policy.max_attempts:
                raise IntegrationRequestFailed(f"retryable provider response persisted: {response.status_code}")
            await asyncio.sleep(self._retry_delay(response, attempt))

        raise IntegrationRequestFailed("bounded integration request failed") from last

    def _is_retryable(self, response: httpx.Response) -> bool:
        if response.status_code in {408, 409, 425, 429} or response.status_code >= 500:
            return True
        if response.status_code == 403:
            return bool(response.headers.get("retry-after")) or response.headers.get("x-ratelimit-remaining") == "0"
        return False

    def _retry_delay(self, response: httpx.Response, attempt: int) -> float:
        retry_after = response.headers.get("retry-after")
        if retry_after:
            try:
                delay = float(retry_after)
                return self._bounded_provider_delay(delay)
            except ValueError:
                pass
        reset = response.headers.get("x-ratelimit-reset")
        if reset and response.headers.get("x-ratelimit-remaining") == "0":
            try:
                delay = max(0.0, float(reset) - time.time())
                return self._bounded_provider_delay(delay)
            except ValueError:
                pass
        return self._exponential_delay(attempt)

    def _bounded_provider_delay(self, delay: float) -> float:
        if delay > self.policy.max_retry_delay_seconds:
            raise IntegrationRequestFailed("provider retry delay exceeds configured bound")
        return max(0.0, delay)

    def _exponential_delay(self, attempt: int) -> float:
        return min(
            self.policy.backoff_base_seconds * (2 ** (attempt - 1)),
            self.policy.max_retry_delay_seconds,
        )
