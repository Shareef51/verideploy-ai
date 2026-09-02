from __future__ import annotations
import time
from contextlib import contextmanager
from typing import Iterator
from sqlalchemy import Connection, text

MIGRATION_LOCK_KEY = 7_336_033_001


class MigrationLockTimeout(TimeoutError):
    pass


@contextmanager
def postgres_migration_lock(
    connection: Connection,
    *,
    lock_key: int = MIGRATION_LOCK_KEY,
    timeout_seconds: float = 120.0,
    poll_interval_seconds: float = 0.25,
) -> Iterator[None]:
    if connection.dialect.name != 'postgresql':
        yield
        return
    deadline = time.monotonic() + timeout_seconds
    acquired = False
    while time.monotonic() < deadline:
        acquired = bool(connection.execute(text('SELECT pg_try_advisory_lock(:lock_key)'), {'lock_key': lock_key}).scalar())
        if acquired:
            break
        time.sleep(poll_interval_seconds)
    if not acquired:
        raise MigrationLockTimeout(f'could not acquire PostgreSQL migration advisory lock within {timeout_seconds:g}s')
    # pg_advisory_lock is session-scoped, not transaction-scoped, so it is safe to commit here.
    # Doing so closes the implicit transaction SQLAlchemy autobegan for the lock statement above,
    # ensuring the caller's own transaction (e.g. Alembic's context.begin_transaction()) starts
    # clean and actually owns and commits its own top-level transaction.
    connection.commit()
    try:
        yield
    finally:
        connection.execute(text('SELECT pg_advisory_unlock(:lock_key)'), {'lock_key': lock_key})
        connection.commit()
