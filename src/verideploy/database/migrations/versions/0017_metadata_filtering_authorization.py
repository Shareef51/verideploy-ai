"""Metadata filtering and authorization columns/indexes."""
from alembic import op
import sqlalchemy as sa
revision="0017_milestone35_metadata_filtering_authorization"
down_revision="0016_milestone34_retrieval_pipeline_orchestration"
branch_labels=None
depends_on=None

def _add(table:str, permission:str)->None:
    op.add_column(table,sa.Column("severity",sa.String(32),nullable=True))
    op.add_column(table,sa.Column("team",sa.String(120),nullable=True))
    op.add_column(table,sa.Column("occurred_at",sa.DateTime(timezone=True),nullable=True))
    op.add_column(table,sa.Column("required_permission",sa.String(120),nullable=False,server_default=permission))

def upgrade()->None:
    _add("retrieval_documents","retrieval.read")
    _add("visual_documents","retrieval.visual.read")
    op.add_column("visual_documents",sa.Column("service",sa.String(120),nullable=True))
    op.add_column("visual_documents",sa.Column("environment",sa.String(80),nullable=True))
    op.add_column("visual_documents",sa.Column("document_kind",sa.String(40),nullable=False,server_default="general"))
    op.execute("UPDATE retrieval_documents SET occurred_at=created_at WHERE occurred_at IS NULL")
    op.execute("UPDATE visual_documents SET occurred_at=created_at WHERE occurred_at IS NULL")
    op.alter_column("retrieval_documents","occurred_at",nullable=False)
    op.alter_column("visual_documents","occurred_at",nullable=False)
    op.create_index("ix_retrieval_metadata","retrieval_documents",["tenant_id","service","environment","document_kind","team","severity","occurred_at"])
    op.create_index("ix_retrieval_permission","retrieval_documents",["tenant_id","required_permission","occurred_at"])
    op.create_index("ix_visual_metadata","visual_documents",["tenant_id","service","environment","document_kind","team","severity","occurred_at"])
    op.create_index("ix_visual_permission","visual_documents",["tenant_id","required_permission","occurred_at"])

def downgrade()->None:
    for table in ("visual_documents","retrieval_documents"):
        op.drop_index(f"ix{'visual' if table=='visual_documents' else 'retrieval'}_permission",table_name=table)
        op.drop_index(f"ix{'visual' if table=='visual_documents' else 'retrieval'}_metadata",table_name=table)
    for c in ("document_kind","environment","service"):
        op.drop_column("visual_documents",c)
    for table in ("visual_documents","retrieval_documents"):
        for c in ("required_permission","occurred_at","team","severity"):
            op.drop_column(table,c)
