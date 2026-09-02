from __future__ import annotations

import socket
from dataclasses import dataclass
from urllib.parse import urlparse
from urllib.request import Request, urlopen


from verideploy.config import Settings


@dataclass(frozen=True)
class ProbeResult:
    name: str
    ok: bool
    detail: str


def _safe_detail(exc: BaseException) -> str:
    # Never put URLs, credentials, tokens, or raw connection strings in health output.
    return exc.__class__.__name__


def probe_postgres(settings: Settings) -> ProbeResult:
    import psycopg

    dsn = settings.database_url.replace("postgresql+psycopg://", "postgresql://", 1)
    try:
        with psycopg.connect(dsn, connect_timeout=max(1, int(settings.platform_readiness_timeout_seconds))) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
        return ProbeResult("postgres", True, "ok")
    except Exception as exc:  # pragma: no cover - concrete driver errors vary by platform
        return ProbeResult("postgres", False, _safe_detail(exc))


def probe_redis(settings: Settings) -> ProbeResult:
    import redis

    try:
        client = redis.Redis.from_url(
            settings.redis_url,
            socket_connect_timeout=settings.platform_readiness_timeout_seconds,
            socket_timeout=settings.platform_readiness_timeout_seconds,
        )
        client.ping()
        client.close()
        return ProbeResult("redis", True, "ok")
    except Exception as exc:  # pragma: no cover
        return ProbeResult("redis", False, _safe_detail(exc))


def probe_kafka(settings: Settings) -> ProbeResult:
    broker = settings.kafka_brokers.split(",", 1)[0].strip()
    host, _, raw_port = broker.partition(":")
    port = int(raw_port or "9092")
    try:
        with socket.create_connection((host, port), timeout=settings.platform_readiness_timeout_seconds):
            pass
        return ProbeResult("kafka", True, "ok")
    except Exception as exc:  # pragma: no cover
        return ProbeResult("kafka", False, _safe_detail(exc))


def probe_object_store(settings: Settings) -> ProbeResult:
    endpoint = settings.s3_endpoint.rstrip("/") + "/minio/health/ready"
    try:
        request = Request(endpoint, method="GET")
        with urlopen(request, timeout=settings.platform_readiness_timeout_seconds) as response:  # noqa: S310 - configured internal endpoint
            ok = 200 <= response.status < 300
        return ProbeResult("object_store", ok, "ok" if ok else "unhealthy")
    except Exception as exc:  # pragma: no cover
        return ProbeResult("object_store", False, _safe_detail(exc))


def probe_all(settings: Settings) -> tuple[ProbeResult, ...]:
    return (
        probe_postgres(settings),
        probe_redis(settings),
        probe_kafka(settings),
        probe_object_store(settings),
    )
