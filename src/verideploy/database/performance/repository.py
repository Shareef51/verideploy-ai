from __future__ import annotations
from uuid import UUID, uuid4
from sqlalchemy import text
from verideploy.database.session import DatabaseManager
from .telemetry import SlowQuerySample


class QueryTelemetryRepository:
    def __init__(self, db: DatabaseManager, *, application_name: str = 'verideploy-ai') -> None:
        self.db = db
        self.application_name = application_name

    def append(self, tenant_id: UUID, sample: SlowQuerySample) -> UUID:
        query_event_id = uuid4()
        with self.db.tenant_session(tenant_id) as session:
            session.execute(text('''
                INSERT INTO database_query_telemetry
                (query_event_id, tenant_id, fingerprint, operation, duration_ms, row_count, application_name, observed_at, payload)
                VALUES (:id, :tenant, :fp, :op, :duration, :rows, :app, :observed, '{}'::jsonb)
            '''), {
                'id': query_event_id, 'tenant': tenant_id, 'fp': sample.fingerprint, 'op': sample.operation,
                'duration': sample.duration_ms, 'rows': sample.rowcount, 'app': self.application_name,
                'observed': sample.observed_at,
            })
            session.commit()
        return query_event_id
