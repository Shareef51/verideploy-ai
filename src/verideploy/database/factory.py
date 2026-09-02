from __future__ import annotations
from verideploy.config import Settings
from verideploy.database.performance.telemetry import SlowQueryTelemetry
from verideploy.database.session import DatabaseManager
from verideploy.observability.telemetry import instrument_sqlalchemy_engine


def create_database_manager(settings: Settings, *, collect_slow_queries: bool = True) -> DatabaseManager:
    telemetry = SlowQueryTelemetry(settings.db_slow_query_threshold_ms) if collect_slow_queries else None
    manager = DatabaseManager(
        settings.database_url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout_seconds=settings.db_pool_timeout_seconds,
        pool_recycle_seconds=settings.db_pool_recycle_seconds,
        slow_query_telemetry=telemetry,
    )
    if settings.otel_enabled:
        instrument_sqlalchemy_engine(manager.engine)
    return manager
