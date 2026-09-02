"""Release-risk screen source metadata.

Revision ID: 0024_milestone45_release_risk_screen
Revises: 0023_milestone42_long_running_workflow_durability
"""
from alembic import op
import sqlalchemy as sa
revision="0024_milestone45_release_risk_screen"
down_revision="0023_milestone42_long_running_workflow_durability"
branch_labels=None
depends_on=None

def upgrade()->None:
    # release_risk_assessments is created lazily by SqlAlchemyReleaseRiskRepository's own
    # create_all() (verideploy.releases.repository), not by an alembic migration. On a fresh
    # database the table does not exist yet; this migration only retrofits databases where an
    # older app version already created it without changed_files_json.
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "release_risk_assessments" not in inspector.get_table_names():
        return
    op.add_column("release_risk_assessments",sa.Column("changed_files_json",sa.Text(),nullable=True))
    op.execute("UPDATE release_risk_assessments SET changed_files_json='[]' WHERE changed_files_json IS NULL")
    op.alter_column("release_risk_assessments","changed_files_json",nullable=False,server_default="[]")
    op.create_index("ix_release_selector","release_risk_assessments",["tenant_id","updated_at","created_at"])

def downgrade()->None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "release_risk_assessments" not in inspector.get_table_names():
        return
    op.drop_index("ix_release_selector",table_name="release_risk_assessments")
    op.drop_column("release_risk_assessments","changed_files_json")
