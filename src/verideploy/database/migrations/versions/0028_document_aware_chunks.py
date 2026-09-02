"""Document-aware retrieval chunk hierarchy.

Revision ID: 0028_document_aware_chunks
Revises: 0027_milestone65_kafka_event_architecture
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0028_document_aware_chunks"
down_revision = "0027_milestone65_kafka_event_architecture"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("retrieval_chunks", sa.Column("chunk_kind", sa.String(64), nullable=False, server_default="document"))
    op.add_column("retrieval_chunks", sa.Column("hierarchy_path", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")))
    op.create_index("ix_retrieval_chunks_kind", "retrieval_chunks", ["tenant_id", "chunk_kind"])


def downgrade() -> None:
    op.drop_index("ix_retrieval_chunks_kind", table_name="retrieval_chunks")
    op.drop_column("retrieval_chunks", "hierarchy_path")
    op.drop_column("retrieval_chunks", "chunk_kind")
