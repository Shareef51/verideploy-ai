from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from verideploy.database.repositories.vector_embeddings import PgVectorEmbeddingRepository, _vector_literal
from verideploy.database.session import DatabaseManager


def test_database_manager_supports_non_postgres_unit_sessions() -> None:
    db = DatabaseManager("sqlite+pysqlite:///:memory:")
    tenant_id = uuid4()
    with db.tenant_session(tenant_id) as session:
        assert isinstance(session, Session)
    db.dispose()


def test_nearest_refuses_non_postgresql_instead_of_faking_vector_search() -> None:
    db = DatabaseManager("sqlite+pysqlite:///:memory:")
    repo = PgVectorEmbeddingRepository(db)
    with pytest.raises(RuntimeError, match="require PostgreSQL"):
        repo.nearest(tenant_id=uuid4(), embedding_model_id=uuid4(), query_vector=[0.1, 0.2], limit=5)


def test_vector_literal_is_numeric_and_bounded_limit_is_enforced() -> None:
    assert _vector_literal([0.1, -2, 3.25]) == "[0.1,-2,3.25]"
    db = DatabaseManager("sqlite+pysqlite:///:memory:")
    repo = PgVectorEmbeddingRepository(db)
    with pytest.raises(ValueError):
        repo.nearest(tenant_id=uuid4(), embedding_model_id=uuid4(), query_vector=[0.1], limit=101)
