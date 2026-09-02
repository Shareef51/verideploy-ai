"""PostgreSQL + pgvector foundation.

Revision ID: 0001_milestone12_pgvector
Revises: None
"""
from alembic import op
import sqlalchemy as sa

revision = "0001_milestone12_pgvector"
down_revision = None
branch_labels = None
depends_on = None

VECTOR_DIMENSIONS = 3072


def _tenant_policy(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {table}_tenant_isolation ON {table} "
        "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
        "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
    )


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "tenants",
        sa.Column("tenant_id", sa.Uuid(), primary_key=True),
        sa.Column("slug", sa.String(length=80), nullable=False, unique=True),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_table(
        "embedding_models",
        sa.Column("embedding_model_id", sa.Uuid(), primary_key=True),
        sa.Column("model_name", sa.String(length=160), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column("registry_version", sa.Integer(), nullable=False),
        sa.Column("index_version", sa.String(length=80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("dimensions > 0", name="ck_embedding_models_dimensions_positive"),
        sa.UniqueConstraint("model_name", "dimensions", "registry_version", name="uq_embedding_model_version"),
    )
    op.execute(
        "INSERT INTO embedding_models "
        "(embedding_model_id, model_name, provider, dimensions, registry_version, index_version) VALUES "
        "('00000000-0000-4000-8000-000000000012', 'text-embedding-3-large', 'openai', 3072, 1, 'v1')"
    )
    op.create_table(
        "vector_embeddings",
        sa.Column("embedding_id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False),
        sa.Column("embedding_model_id", sa.Uuid(), sa.ForeignKey("embedding_models.embedding_model_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=True),
        sa.Column("chunk_id", sa.Uuid(), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=24), nullable=False),
        sa.Column("provider_request_id", sa.String(length=256), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(f"dimensions = {VECTOR_DIMENSIONS}", name="ck_vector_embeddings_dimensions"),
        sa.UniqueConstraint("tenant_id", "content_hash", "embedding_model_id", name="uq_vector_embedding_content"),
    )
    op.execute(f"ALTER TABLE vector_embeddings ADD COLUMN embedding vector({VECTOR_DIMENSIONS}) NOT NULL")
    op.create_index("ix_vector_embeddings_tenant_model", "vector_embeddings", ["tenant_id", "embedding_model_id"])
    op.create_index("ix_vector_embeddings_tenant_state", "vector_embeddings", ["tenant_id", "state"])
    op.execute(
        "CREATE INDEX ix_vector_embeddings_hnsw_cosine ON vector_embeddings "
        f"USING hnsw ((embedding::halfvec({VECTOR_DIMENSIONS})) halfvec_cosine_ops) WITH (m = 16, ef_construction = 64)"
    )
    _tenant_policy("vector_embeddings")


def downgrade() -> None:
    op.drop_table("vector_embeddings")
    op.drop_table("embedding_models")
    op.drop_table("tenants")
    # Deliberately retain the shared vector extension; other schemas may depend on it.
