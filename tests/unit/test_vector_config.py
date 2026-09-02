from pathlib import Path

import pytest

from verideploy.database.models.embedding import VECTOR_DIMENSIONS
from verideploy.database.vector_config import load_vector_index_config, validate_embedding_settings


def test_vector_config_matches_migration_decision() -> None:
    config = load_vector_index_config("config/vector-index.json")
    assert config.dimensions == VECTOR_DIMENSIONS == 3072
    assert config.distance == "cosine"
    assert config.index_type == "hnsw"
    assert config.migration_revision == "0001_milestone12_pgvector"


def test_embedding_configuration_drift_is_rejected() -> None:
    config = load_vector_index_config("config/vector-index.json")
    with pytest.raises(ValueError, match="new re-embedding/index migration"):
        validate_embedding_settings(config=config, model="other-model", dimensions=config.dimensions)
    with pytest.raises(ValueError):
        validate_embedding_settings(config=config, model=config.embedding_model, dimensions=1536)


def test_migration_contains_pgvector_hnsw_rls_and_safe_downgrade() -> None:
    source = Path("src/verideploy/database/migrations/versions/0001_pgvector.py").read_text()
    assert "CREATE EXTENSION IF NOT EXISTS vector" in source
    assert "VECTOR_DIMENSIONS = 3072" in source
    assert "vector({VECTOR_DIMENSIONS})" in source
    assert "USING hnsw" in source
    assert "vector_cosine_ops" in source
    assert "provider_request_id" in source
    assert "prompt_tokens" in source
    assert "ENABLE ROW LEVEL SECURITY" in source
    assert "FORCE ROW LEVEL SECURITY" in source
    assert "DROP EXTENSION" not in source.upper()
