from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from typing import Any, Iterator, Mapping, MutableMapping

from verideploy.config import Settings

log = logging.getLogger(__name__)
_CONFIGURED: set[str] = set()

SENSITIVE_ATTRIBUTE_TOKENS = (
    "authorization", "cookie", "password", "secret", "token", "api_key", "apikey", "body", "prompt", "document"
)


def _safe_attributes(values: Mapping[str, Any] | None) -> dict[str, Any]:
    if not values:
        return {}
    safe: dict[str, Any] = {}
    for key, value in values.items():
        lowered = key.lower()
        if any(token in lowered for token in SENSITIVE_ATTRIBUTE_TOKENS):
            continue
        if value is None or isinstance(value, (str, bool, int, float)):
            safe[key] = value
        else:
            safe[key] = str(value)[:256]
    return safe


def configure_telemetry(settings: Settings, *, service_name: str, fastapi_app: Any | None = None) -> bool:
    """Configure OTLP tracing once per process. Disabled mode is intentionally no-op."""
    if not settings.otel_enabled or service_name in _CONFIGURED:
        return False
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.semconv.resource import ResourceAttributes

        resource = Resource.create({
            ResourceAttributes.SERVICE_NAME: service_name,
            ResourceAttributes.SERVICE_VERSION: os.getenv("VERIDEPLOY_VERSION", "0.50.0"),
            ResourceAttributes.DEPLOYMENT_ENVIRONMENT: settings.app_env,
            "service.namespace": "verideploy",
        })
        provider = TracerProvider(resource=resource, sampler=ParentBased(TraceIdRatioBased(settings.otel_traces_sampler_arg)))
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_endpoint, insecure=settings.otel_exporter_otlp_insecure)))
        trace.set_tracer_provider(provider)

        # Library instrumentation is deliberately centralized here to keep trace context continuous.
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        from opentelemetry.instrumentation.redis import RedisInstrumentor
        HTTPXClientInstrumentor().instrument()
        RedisInstrumentor().instrument()

        if fastapi_app is not None:
            from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
            FastAPIInstrumentor.instrument_app(
                fastapi_app,
                excluded_urls=settings.otel_excluded_urls,
                server_request_hook=_server_request_hook,
            )
        _CONFIGURED.add(service_name)
        log.info("otel_configured", extra={"service_name": service_name, "endpoint": settings.otel_exporter_otlp_endpoint})
        return True
    except Exception:
        log.exception("otel_configuration_failed", extra={"service_name": service_name})
        if settings.app_env in {"staging", "production"}:
            raise
        return False


def instrument_sqlalchemy_engine(engine: Any) -> None:
    try:
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
        SQLAlchemyInstrumentor().instrument(engine=engine)
    except Exception:
        log.exception("otel_sqlalchemy_instrumentation_failed")


def _server_request_hook(span: Any, scope: Mapping[str, Any]) -> None:
    if not getattr(span, "is_recording", lambda: False)():
        return
    headers = {k.decode().lower(): v.decode(errors="ignore") for k, v in scope.get("headers", [])}
    for key in ("x-correlation-id", "x-tenant-id"):
        if value := headers.get(key):
            span.set_attribute(f"verideploy.{key[2:].replace('-', '_')}", value[:128])


def inject_trace_headers(headers: MutableMapping[str, str] | None = None) -> MutableMapping[str, str]:
    carrier: MutableMapping[str, str] = headers if headers is not None else {}
    try:
        from opentelemetry.propagate import inject
        inject(carrier)
    except Exception:
        pass
    return carrier


def inject_kafka_headers(headers: list[tuple[str, bytes]] | None = None) -> list[tuple[str, bytes]]:
    base = list(headers or [])
    carrier: dict[str, str] = {}
    inject_trace_headers(carrier)
    existing = {k.lower() for k, _ in base}
    for key, value in carrier.items():
        if key.lower() not in existing:
            base.append((key, value.encode()))
    return base


def extract_kafka_context(headers: list[tuple[str, bytes]] | None) -> Any:
    try:
        from opentelemetry.propagate import extract
        carrier = {k: v.decode(errors="ignore") for k, v in (headers or [])}
        return extract(carrier)
    except Exception:
        return None


@contextmanager
def span(name: str, *, attributes: Mapping[str, Any] | None = None, context: Any | None = None) -> Iterator[Any]:
    try:
        from opentelemetry import trace
        tracer = trace.get_tracer("verideploy")
        manager = tracer.start_as_current_span(name, context=context, attributes=_safe_attributes(attributes))
    except Exception:
        yield None
        return
    with manager as current:
        yield current


def traced_async(name: str):
    """Decorator for explicit async application spans such as LangGraph/RAG/MCP boundaries."""
    def decorator(fn):
        async def wrapped(*args: Any, **kwargs: Any):
            with span(name):
                return await fn(*args, **kwargs)
        wrapped.__name__ = getattr(fn, "__name__", "wrapped")
        wrapped.__doc__ = getattr(fn, "__doc__", None)
        return wrapped
    return decorator
