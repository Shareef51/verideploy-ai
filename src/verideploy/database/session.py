from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Iterator
from uuid import UUID

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from verideploy.database.performance.budgets import QueryBudget
from verideploy.database.performance.telemetry import SlowQueryTelemetry


class DatabaseManager:
    def __init__(
        self,
        database_url: str,
        *,
        pool_size: int = 10,
        max_overflow: int = 20,
        pool_timeout_seconds: float = 30.0,
        pool_recycle_seconds: int = 1_800,
        slow_query_telemetry: SlowQueryTelemetry | None = None,
    ) -> None:
        kwargs: dict[str, object] = {'future': True, 'pool_pre_ping': True}
        if database_url.startswith('postgresql'):
            kwargs.update(
                pool_size=pool_size,
                max_overflow=max_overflow,
                pool_timeout=pool_timeout_seconds,
                pool_recycle=pool_recycle_seconds,
                pool_use_lifo=True,
            )
        self.engine: Engine = create_engine(database_url, **kwargs)
        self._session_factory = sessionmaker(bind=self.engine, expire_on_commit=False, future=True)
        self.slow_query_telemetry = slow_query_telemetry
        if slow_query_telemetry is not None:
            self._install_query_telemetry(slow_query_telemetry)

    def _install_query_telemetry(self, telemetry: SlowQueryTelemetry) -> None:
        @event.listens_for(self.engine, 'before_cursor_execute')
        def _before(_conn, _cursor, _statement, _parameters, context, _executemany):  # type: ignore[no-untyped-def]
            context._verideploy_started_at = time.perf_counter()

        @event.listens_for(self.engine, 'after_cursor_execute')
        def _after(_conn, cursor, statement, _parameters, context, _executemany):  # type: ignore[no-untyped-def]
            started = getattr(context, '_verideploy_started_at', None)
            if started is None:
                return
            telemetry.record(statement, duration_ms=(time.perf_counter() - started) * 1000.0, rowcount=getattr(cursor, 'rowcount', None))

    @contextmanager
    def tenant_session(
        self,
        tenant_id: UUID,
        *,
        statement_timeout_ms: int = 15_000,
        lock_timeout_ms: int = 2_000,
        idle_in_transaction_timeout_ms: int = 30_000,
        budget: QueryBudget | None = None,
    ) -> Iterator[Session]:
        session = self._session_factory()
        try:
            effective = budget or QueryBudget(
                statement_timeout_ms=statement_timeout_ms,
                lock_timeout_ms=lock_timeout_ms,
                idle_in_transaction_timeout_ms=idle_in_transaction_timeout_ms,
            )
            if self.engine.dialect.name == 'postgresql':
                session.execute(text("SELECT set_config('app.tenant_id', :tenant_id, true)"), {'tenant_id': str(tenant_id)})
                for key, value in (
                    ('statement_timeout', effective.statement_timeout_ms),
                    ('lock_timeout', effective.lock_timeout_ms),
                    ('idle_in_transaction_session_timeout', effective.idle_in_transaction_timeout_ms),
                ):
                    session.execute(text("SELECT set_config(:name, :value, true)"), {'name': key, 'value': f'{value}ms'})
            yield session
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def pool_status(self) -> str:
        return self.engine.pool.status()

    def dispose(self) -> None:
        self.engine.dispose()
