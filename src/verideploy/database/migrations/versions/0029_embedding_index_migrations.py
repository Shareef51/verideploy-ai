"""Safe embedding index migrations and shadow quality measurements."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
revision="0029_embedding_index_migrations";down_revision="0028_document_aware_chunks";branch_labels=None;depends_on=None
def upgrade():
    op.create_table("embedding_index_versions",sa.Column("index_name",sa.String(80),primary_key=True),sa.Column("model_name",sa.String(128),nullable=False),sa.Column("dimensions",sa.Integer(),nullable=False),sa.Column("phase",sa.String(24),nullable=False),sa.Column("write_enabled",sa.Boolean(),nullable=False,server_default=sa.false()),sa.Column("read_enabled",sa.Boolean(),nullable=False,server_default=sa.false()),sa.Column("created_at",sa.DateTime(timezone=True),server_default=sa.text("now()"),nullable=False))
    op.create_table("embedding_shadow_evaluations",sa.Column("evaluation_id",sa.Uuid(),primary_key=True),sa.Column("source_index",sa.String(80),nullable=False),sa.Column("target_index",sa.String(80),nullable=False),sa.Column("sample_size",sa.Integer(),nullable=False),sa.Column("recall",sa.Float(),nullable=False),sa.Column("mrr",sa.Float(),nullable=False),sa.Column("ndcg",sa.Float(),nullable=False),sa.Column("metrics",postgresql.JSONB(),nullable=False),sa.Column("created_at",sa.DateTime(timezone=True),server_default=sa.text("now()"),nullable=False))
def downgrade():
    op.drop_table("embedding_shadow_evaluations");op.drop_table("embedding_index_versions")
