from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import Column, MetaData, String, Table, engine_from_config, pool

from verideploy.database.base import Base
from verideploy.database import models  # noqa: F401
from verideploy.database.migration_lock import postgres_migration_lock

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)
config.set_main_option("sqlalchemy.url", os.getenv("DATABASE_URL", config.get_main_option("sqlalchemy.url")))
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"), target_metadata=target_metadata, literal_binds=True, compare_type=True
    )
    with context.begin_transaction():
        context.run_migrations()


def _ensure_wide_version_table(connection) -> None:
    # Alembic's default version_num column is VARCHAR(32); this project's descriptive
    # revision ids (e.g. "0003_milestone14_visual_document_retrieval") exceed that width.
    # Pre-create the table with a wider column; Alembic only creates it if absent.
    table = Table(
        "alembic_version", MetaData(),
        Column("version_num", String(255), primary_key=True, nullable=False),
    )
    table.create(connection, checkfirst=True)


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}), prefix="sqlalchemy.", poolclass=pool.NullPool
    )
    with connectable.connect() as connection:
        with postgres_migration_lock(connection, timeout_seconds=float(os.getenv('DB_MIGRATION_LOCK_TIMEOUT_SECONDS', '120'))):
            _ensure_wide_version_table(connection)
            context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
            with context.begin_transaction():
                context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
