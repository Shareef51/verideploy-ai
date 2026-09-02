from __future__ import annotations

from sqlalchemy import create_engine, text

from verideploy.config import get_settings
from verideploy.database.vector_config import load_vector_index_config, validate_embedding_settings


def main() -> None:
    settings = get_settings()
    config = load_vector_index_config(settings.vector_index_config_path)
    validate_embedding_settings(
        config=config, model=settings.openai_embedding_model, dimensions=settings.openai_embedding_dimensions
    )
    engine = create_engine(settings.database_url, future=True)
    with engine.connect() as connection:
        if connection.dialect.name != "postgresql":
            raise SystemExit("database check requires PostgreSQL")
        extension = connection.scalar(text("SELECT extversion FROM pg_extension WHERE extname='vector'"))
        if not extension:
            raise SystemExit("pgvector extension is not installed")
        index = connection.scalar(
            text("SELECT indexname FROM pg_indexes WHERE indexname='ix_vector_embeddings_hnsw_cosine'")
        )
        if not index:
            raise SystemExit("HNSW index is missing")
        rls = connection.scalar(
            text("SELECT relrowsecurity FROM pg_class WHERE oid='vector_embeddings'::regclass")
        )
        if not rls:
            raise SystemExit("RLS is not enabled for vector_embeddings")
        print(f"pgvector={extension} hnsw={index} rls={rls} index_version={config.index_version}")


if __name__ == "__main__":
    main()
