from pathlib import Path


def test_runtime_embedding_factory_uses_pgvector_repository_for_non_test_postgres() -> None:
    source = Path("services/ai/embedding_pipeline.py").read_text()
    assert "PgVectorEmbeddingCacheRepository" in source
    assert "validate_embedding_settings" in source
    assert "settings.app_env == \"test\"" in source
