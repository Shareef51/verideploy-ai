"""Visual document retrieval indexes.

Revision ID: 0003_milestone14_visual_document_retrieval
Revises: 0002_milestone13_hybrid_retrieval
"""
from alembic import op
import sqlalchemy as sa
revision="0003_milestone14_visual_document_retrieval"; down_revision="0002_milestone13_hybrid_retrieval"; branch_labels=None; depends_on=None

def _tenant_policy(table:str)->None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY {table}_tenant_isolation ON {table} USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)")

def upgrade()->None:
    op.create_table("visual_documents",
        sa.Column("document_id",sa.Uuid(),primary_key=True),sa.Column("tenant_id",sa.Uuid(),sa.ForeignKey("tenants.tenant_id",ondelete="CASCADE"),nullable=False),
        sa.Column("source_key",sa.String(240),nullable=False),sa.Column("title",sa.String(500),nullable=False),sa.Column("created_at",sa.DateTime(timezone=True),server_default=sa.text("now()"),nullable=False),
        sa.UniqueConstraint("tenant_id","source_key",name="uq_visual_document_source"))
    op.create_table("visual_pages",
        sa.Column("page_id",sa.Uuid(),primary_key=True),sa.Column("tenant_id",sa.Uuid(),sa.ForeignKey("tenants.tenant_id",ondelete="CASCADE"),nullable=False),
        sa.Column("document_id",sa.Uuid(),sa.ForeignKey("visual_documents.document_id",ondelete="CASCADE"),nullable=False),sa.Column("page_number",sa.Integer(),nullable=False),
        sa.Column("image_path",sa.Text(),nullable=False),sa.Column("image_sha256",sa.String(64),nullable=False),sa.Column("width",sa.Integer(),nullable=False),sa.Column("height",sa.Integer(),nullable=False),sa.Column("native_text",sa.Text(),nullable=False,server_default=""),sa.Column("created_at",sa.DateTime(timezone=True),server_default=sa.text("now()"),nullable=False),
        sa.CheckConstraint("page_number >= 1",name="ck_visual_page_number"),sa.UniqueConstraint("tenant_id","document_id","page_number",name="uq_visual_page_ordinal"))
    op.create_table("visual_page_indexes",
        sa.Column("index_id",sa.Uuid(),primary_key=True),sa.Column("tenant_id",sa.Uuid(),sa.ForeignKey("tenants.tenant_id",ondelete="CASCADE"),nullable=False),sa.Column("page_id",sa.Uuid(),sa.ForeignKey("visual_pages.page_id",ondelete="CASCADE"),nullable=False),
        sa.Column("backend",sa.String(40),nullable=False),sa.Column("model_name",sa.String(240),nullable=False),sa.Column("index_version",sa.String(80),nullable=False),sa.Column("embedding_ref",sa.Text(),nullable=True),sa.Column("feature_json",sa.JSON(),nullable=True),sa.Column("created_at",sa.DateTime(timezone=True),server_default=sa.text("now()"),nullable=False),
        sa.UniqueConstraint("tenant_id","page_id","backend","model_name","index_version",name="uq_visual_page_index"))
    op.create_index("ix_visual_pages_tenant_document","visual_pages",["tenant_id","document_id"])
    op.create_index("ix_visual_index_lookup","visual_page_indexes",["tenant_id","backend","model_name"])
    for t in ("visual_documents","visual_pages","visual_page_indexes"): _tenant_policy(t)

def downgrade()->None:
    op.drop_table("visual_page_indexes");op.drop_table("visual_pages");op.drop_table("visual_documents")
