"""Hybrid retrieval corpus and PostgreSQL FTS index.

Revision ID: 0002_milestone13_hybrid_retrieval
Revises: 0001_milestone12_pgvector
"""
from alembic import op
import sqlalchemy as sa

revision = "0002_milestone13_hybrid_retrieval"
down_revision = "0001_milestone12_pgvector"
branch_labels = None
depends_on = None


def _tenant_policy(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {table}_tenant_isolation ON {table} "
        "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
        "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
    )


def upgrade() -> None:
    op.create_table(
        "retrieval_documents",
        sa.Column("document_id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_key", sa.String(length=240), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("service", sa.String(length=120), nullable=True),
        sa.Column("environment", sa.String(length=80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("tenant_id", "source_key", name="uq_retrieval_document_source"),
    )
    op.create_index("ix_retrieval_documents_tenant_service", "retrieval_documents", ["tenant_id", "service"])
    op.create_table(
        "retrieval_chunks",
        sa.Column("chunk_id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False),
        sa.Column("document_id", sa.Uuid(), sa.ForeignKey("retrieval_documents.document_id", ondelete="CASCADE"), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("ordinal >= 0", name="ck_retrieval_chunks_ordinal_nonnegative"),
        sa.UniqueConstraint("tenant_id", "document_id", "ordinal", name="uq_retrieval_chunk_ordinal"),
    )
    op.execute(
        "ALTER TABLE retrieval_chunks ADD COLUMN search_vector tsvector GENERATED ALWAYS AS "
        "(to_tsvector('english'::regconfig, coalesce(content, ''))) STORED"
    )
    op.create_index("ix_retrieval_chunks_tenant_document", "retrieval_chunks", ["tenant_id", "document_id"])
    op.execute("CREATE INDEX ix_retrieval_chunks_search_gin ON retrieval_chunks USING gin (search_vector)")
    _tenant_policy("retrieval_documents")
    _tenant_policy("retrieval_chunks")


def downgrade() -> None:
    op.drop_table("retrieval_chunks")
    op.drop_table("retrieval_documents")
