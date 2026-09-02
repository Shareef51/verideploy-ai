from __future__ import annotations

from sqlalchemy import create_engine, text

from verideploy.config import get_settings


def main() -> None:
    settings = get_settings()
    engine = create_engine(settings.database_url, future=True)
    checks = {
        "alembic_revision": "SELECT version_num FROM alembic_version",
        "pgvector": "SELECT extversion FROM pg_extension WHERE extname='vector'",
        "hnsw_index": "SELECT indexname FROM pg_indexes WHERE indexname='ix_vector_embeddings_hnsw_cosine'",
        "rls": "SELECT relrowsecurity FROM pg_class WHERE oid='vector_embeddings'::regclass",
        "forced_rls": "SELECT relforcerowsecurity FROM pg_class WHERE oid='vector_embeddings'::regclass",
    }
    with engine.connect() as connection:
        results = {name: connection.scalar(text(sql)) for name, sql in checks.items()}
    failures = [name for name, value in results.items() if value in (None, False, "")]
    if failures:
        raise SystemExit(f"restore verification failed: {', '.join(failures)}")
    print("restore verification passed", results)


if __name__ == "__main__":
    main()
