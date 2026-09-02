"""Retrieval document kinds for RAGAgent metadata filtering.

Revision ID: 0008_milestone20_rag_agent
Revises: 0007_milestone19_agent_contracts
"""
from alembic import op
import sqlalchemy as sa

revision = "0008_milestone20_rag_agent"
down_revision = "0007_milestone19_agent_contracts"
branch_labels = None
depends_on = None

_ALLOWED = "'historical_incident','runbook','architecture','general'"


def upgrade() -> None:
    op.add_column(
        "retrieval_documents",
        sa.Column("document_kind", sa.String(length=40), nullable=False, server_default="general"),
    )
    op.create_check_constraint(
        "ck_retrieval_document_kind",
        "retrieval_documents",
        f"document_kind IN ({_ALLOWED})",
    )
    op.create_index(
        "ix_retrieval_documents_tenant_kind",
        "retrieval_documents",
        ["tenant_id", "document_kind"],
    )


def downgrade() -> None:
    op.drop_index("ix_retrieval_documents_tenant_kind", table_name="retrieval_documents")
    op.drop_constraint("ck_retrieval_document_kind", "retrieval_documents", type_="check")
    op.drop_column("retrieval_documents", "document_kind")
