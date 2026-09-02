from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol
from uuid import UUID, uuid5

from pydantic import BaseModel, Field

from verideploy.llmops.service import redact_payload

_LANGSMITH_NAMESPACE = UUID("7da7ff0a-6b5c-55a2-8797-4cd431e2376a")


class LangSmithStatus(BaseModel):
    enabled: bool
    configured: bool
    project_name: str
    environment: str
    dataset_export_enabled: bool = False
    last_error: str | None = None


class LangSmithClientProtocol(Protocol):
    def create_run(self, **kwargs: Any) -> Any: ...
    def update_run(self, run_id: UUID, **kwargs: Any) -> Any: ...


@dataclass(frozen=True)
class _RunIds:
    root: UUID
    child: UUID


def _safe_text(value: Any, *, max_len: int = 4096) -> str:
    text = str(value)
    return text if len(text) <= max_len else text[: max_len - 3] + "..."


def _canonical_hash(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


class NullLangSmithObserver:
    """Disabled observer. It intentionally has the same non-throwing contract as the live adapter."""

    def __init__(self, *, environment: str, project_name: str, dataset_export_enabled: bool = False) -> None:
        self._status = LangSmithStatus(
            enabled=False,
            configured=False,
            project_name=project_name,
            environment=environment,
            dataset_export_enabled=dataset_export_enabled,
        )

    @property
    def status(self) -> LangSmithStatus:
        return self._status

    async def model_success(self, *, request: Any, result: Any, latency_ms: float) -> None:
        return None

    async def model_failure(
        self,
        *,
        request: Any,
        model: str,
        role: str,
        retry_count: int,
        latency_ms: float,
        error_code: str,
    ) -> None:
        return None

    def trace_fact(self, **_: Any) -> None:
        return None


class LangSmithObserver(NullLangSmithObserver):
    """Best-effort LangSmith exporter.

    Business code must never depend on this adapter. All SDK/network exceptions are captured in status
    and never re-raised to the caller.
    """

    def __init__(
        self,
        *,
        client: LangSmithClientProtocol,
        environment: str,
        project_name: str,
        dataset_export_enabled: bool = False,
    ) -> None:
        super().__init__(
            environment=environment,
            project_name=project_name,
            dataset_export_enabled=dataset_export_enabled,
        )
        self.client = client
        self.environment = environment
        self.project_name = project_name
        self.dataset_export_enabled = dataset_export_enabled
        self._roots: set[UUID] = set()
        self._status = LangSmithStatus(
            enabled=True,
            configured=True,
            project_name=project_name,
            environment=environment,
            dataset_export_enabled=dataset_export_enabled,
        )

    @property
    def status(self) -> LangSmithStatus:
        return self._status

    def _set_error(self, exc: Exception) -> None:
        self._status = self._status.model_copy(update={"last_error": f"{type(exc).__name__}: {_safe_text(exc, max_len=300)}"})

    def _ids(self, *, tenant_id: UUID, correlation_id: str, child_key: str) -> _RunIds:
        root = uuid5(_LANGSMITH_NAMESPACE, f"root:{tenant_id}:{correlation_id}")
        child = uuid5(_LANGSMITH_NAMESPACE, f"child:{tenant_id}:{correlation_id}:{child_key}")
        return _RunIds(root=root, child=child)

    def _ensure_root(self, *, tenant_id: UUID, correlation_id: str) -> UUID:
        ids = self._ids(tenant_id=tenant_id, correlation_id=correlation_id, child_key="root")
        if ids.root in self._roots:
            return ids.root
        self.client.create_run(
            id=ids.root,
            name="verideploy.correlation",
            run_type="chain",
            inputs={"correlation_id": correlation_id},
            project_name=self.project_name,
            tags=["verideploy", self.environment, "correlation-root"],
            extra={
                "metadata": {
                    "environment": self.environment,
                    "tenant_id": str(tenant_id),
                    "correlation_id": correlation_id,
                }
            },
            start_time=datetime.now(timezone.utc),
        )
        self._roots.add(ids.root)
        return ids.root

    async def model_success(self, *, request: Any, result: Any, latency_ms: float) -> None:
        try:
            root = self._ensure_root(tenant_id=request.tenant_id, correlation_id=request.correlation_id)
            ids = self._ids(
                tenant_id=request.tenant_id,
                correlation_id=request.correlation_id,
                child_key=f"model:{request.request_id}",
            )
            md = redact_payload(dict(request.metadata or {}))
            inputs = {
                "operation": request.operation,
                "prompt_sha256": md.get("prompt_sha256"),
                "input_sha256": _canonical_hash(request.input),
            }
            outputs = {
                "status": getattr(result.response_status, "value", str(result.response_status)),
                "output_sha256": _canonical_hash(result.output_text),
                "provider_response_id": result.provider_response_id,
            }
            usage = result.usage
            self.client.create_run(
                id=ids.child,
                name=request.operation,
                run_type="llm",
                inputs=inputs,
                parent_run_id=root,
                project_name=self.project_name,
                tags=["verideploy", self.environment, "model"],
                extra={
                    "metadata": {
                        "environment": self.environment,
                        "tenant_id": str(request.tenant_id),
                        "correlation_id": request.correlation_id,
                        "prompt_name": md.get("prompt_name"),
                        "prompt_version": md.get("prompt_version"),
                        "model_role": result.model_role.value if result.model_role else None,
                        "model": result.model,
                        "input_tokens": usage.input_tokens or 0,
                        "output_tokens": usage.output_tokens or 0,
                        "total_tokens": usage.total_tokens or 0,
                        "latency_ms": round(float(latency_ms), 3),
                        "cost_usd": float(result.actual_cost_usd or result.estimated_cost_usd or 0),
                        "retry_count": max(0, result.attempts - 1),
                    }
                },
                start_time=datetime.now(timezone.utc),
            )
            self.client.update_run(ids.child, outputs=outputs, end_time=datetime.now(timezone.utc))
        except Exception as exc:  # observability must never alter the business result
            self._set_error(exc)

    async def model_failure(
        self,
        *,
        request: Any,
        model: str,
        role: str,
        retry_count: int,
        latency_ms: float,
        error_code: str,
    ) -> None:
        try:
            root = self._ensure_root(tenant_id=request.tenant_id, correlation_id=request.correlation_id)
            ids = self._ids(
                tenant_id=request.tenant_id,
                correlation_id=request.correlation_id,
                child_key=f"model:{request.request_id}:failure:{model}",
            )
            self.client.create_run(
                id=ids.child,
                name=request.operation,
                run_type="llm",
                inputs={"operation": request.operation, "input_sha256": _canonical_hash(request.input)},
                parent_run_id=root,
                project_name=self.project_name,
                tags=["verideploy", self.environment, "model", "failure"],
                extra={"metadata": {
                    "environment": self.environment,
                    "tenant_id": str(request.tenant_id),
                    "correlation_id": request.correlation_id,
                    "model": model,
                    "model_role": role,
                    "retry_count": retry_count,
                    "latency_ms": round(float(latency_ms), 3),
                }},
                start_time=datetime.now(timezone.utc),
            )
            self.client.update_run(ids.child, error=error_code, end_time=datetime.now(timezone.utc))
        except Exception as exc:
            self._set_error(exc)

    def trace_fact(
        self,
        *,
        tenant_id: UUID,
        correlation_id: str,
        span_key: str,
        name: str,
        run_type: str,
        inputs: dict[str, Any] | None = None,
        outputs: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        """Generic child-span hook for retrieval/tool/agent integrations."""
        try:
            root = self._ensure_root(tenant_id=tenant_id, correlation_id=correlation_id)
            ids = self._ids(tenant_id=tenant_id, correlation_id=correlation_id, child_key=span_key)
            safe_inputs = redact_payload(inputs or {})
            safe_outputs = redact_payload(outputs or {})
            safe_metadata = redact_payload(metadata or {})
            self.client.create_run(
                id=ids.child,
                name=name,
                run_type=run_type,
                inputs=safe_inputs,
                parent_run_id=root,
                project_name=self.project_name,
                tags=["verideploy", self.environment, run_type],
                extra={"metadata": {
                    "environment": self.environment,
                    "tenant_id": str(tenant_id),
                    "correlation_id": correlation_id,
                    **safe_metadata,
                }},
                start_time=datetime.now(timezone.utc),
            )
            self.client.update_run(
                ids.child,
                outputs=safe_outputs,
                error=error,
                end_time=datetime.now(timezone.utc),
            )
        except Exception as exc:
            self._set_error(exc)


class LangSmithDatasetHook:
    """Explicit, opt-in dataset export. No production execution calls this automatically."""

    def __init__(
        self,
        *,
        client: Any | None,
        enabled: bool,
        environment: str,
        dataset_prefix: str,
    ) -> None:
        self.client = client
        self.enabled = enabled and client is not None
        self.environment = environment
        self.dataset_prefix = dataset_prefix
        self.last_error: str | None = None

    def dataset_name(self, logical_name: str) -> str:
        safe = "-".join(part for part in logical_name.strip().lower().replace("_", "-").split("-") if part)
        if not safe:
            raise ValueError("logical dataset name must not be blank")
        return f"{self.dataset_prefix}-{self.environment}-{safe}"

    def export_example(
        self,
        *,
        logical_dataset: str,
        inputs: dict[str, Any],
        outputs: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        if not self.enabled:
            return False
        try:
            name = self.dataset_name(logical_dataset)
            exists = False
            if hasattr(self.client, "has_dataset"):
                exists = bool(self.client.has_dataset(dataset_name=name))
            if not exists:
                try:
                    self.client.create_dataset(dataset_name=name, description=f"VeriDeploy {self.environment} evaluation dataset")
                except Exception as exc:
                    # Creating an already-existing dataset may race; continue to example creation.
                    if "exist" not in str(exc).lower() and "409" not in str(exc):
                        raise
            safe_inputs = redact_payload(inputs)
            safe_outputs = redact_payload(outputs or {})
            safe_metadata = {"environment": self.environment, **redact_payload(metadata or {})}
            if hasattr(self.client, "create_example"):
                self.client.create_example(
                    dataset_name=name,
                    inputs=safe_inputs,
                    outputs=safe_outputs,
                    metadata=safe_metadata,
                )
            else:
                self.client.create_examples(
                    dataset_name=name,
                    inputs=[safe_inputs],
                    outputs=[safe_outputs],
                    metadata=[safe_metadata],
                )
            return True
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {_safe_text(exc, max_len=300)}"
            return False


def build_langsmith_observer(settings: Any, *, client: Any | None = None) -> NullLangSmithObserver:
    project = f"{settings.langsmith_project_prefix}-{settings.app_env}"
    if not settings.langsmith_enabled:
        return NullLangSmithObserver(
            environment=settings.app_env,
            project_name=project,
            dataset_export_enabled=settings.langsmith_dataset_export_enabled,
        )
    if client is None:
        try:
            from langsmith import Client

            client = Client(
                api_key=settings.langsmith_api_key.get_secret_value() if settings.langsmith_api_key else None,
                api_url=settings.langsmith_endpoint,
                workspace_id=settings.langsmith_workspace_id,
            )
        except Exception as exc:
            observer = NullLangSmithObserver(
                environment=settings.app_env,
                project_name=project,
                dataset_export_enabled=settings.langsmith_dataset_export_enabled,
            )
            observer._status = observer.status.model_copy(
                update={"enabled": True, "last_error": f"{type(exc).__name__}: {_safe_text(exc, max_len=300)}"}
            )
            return observer
    return LangSmithObserver(
        client=client,
        environment=settings.app_env,
        project_name=project,
        dataset_export_enabled=settings.langsmith_dataset_export_enabled,
    )
