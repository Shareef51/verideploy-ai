from pathlib import Path


def test_hybrid_retrieval_migration_has_fts_gin_rls_and_is_reversible():
    source = Path("src/verideploy/database/migrations/versions/0002_hybrid_retrieval.py").read_text()
    assert 'down_revision = "0001_milestone12_pgvector"' in source
    assert "search_vector tsvector GENERATED ALWAYS" in source
    assert "USING gin (search_vector)" in source
    assert "ENABLE ROW LEVEL SECURITY" in source
    assert "FORCE ROW LEVEL SECURITY" in source
    assert 'op.drop_table("retrieval_chunks")' in source
    assert 'op.drop_table("retrieval_documents")' in source
