"""Long-running workflow durability.

Revision ID: 0023_milestone42_long_running_workflow_durability
Revises: 0022_milestone41_human_approval
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision="0023_milestone42_long_running_workflow_durability"
down_revision="0022_milestone41_human_approval"
branch_labels=None
depends_on=None


def _rls(table:str)->None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY {table}_tenant_isolation ON {table} USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)")


def upgrade()->None:
    op.create_table(
        "workflow_leases",
        sa.Column("lease_id",sa.Uuid(),primary_key=True),
        sa.Column("tenant_id",sa.Uuid(),sa.ForeignKey("tenants.tenant_id",ondelete="CASCADE"),nullable=False),
        sa.Column("run_id",sa.Uuid(),sa.ForeignKey("graph_runs.run_id",ondelete="CASCADE"),nullable=False),
        sa.Column("owner_id",sa.String(256),nullable=False),
        sa.Column("lease_token",sa.Uuid(),nullable=False),
        sa.Column("version",sa.Integer(),nullable=False,server_default="1"),
        sa.Column("acquired_at",sa.DateTime(timezone=True),nullable=False),
        sa.Column("heartbeat_at",sa.DateTime(timezone=True),nullable=False),
        sa.Column("expires_at",sa.DateTime(timezone=True),nullable=False),
        sa.Column("cancelled_at",sa.DateTime(timezone=True),nullable=True),
        sa.UniqueConstraint("tenant_id","run_id",name="uq_lease_run"),
        sa.CheckConstraint("version >= 1",name="ck_lease_version"),
        sa.CheckConstraint("expires_at >= heartbeat_at",name="ck_lease_expiry"),
    )
    op.create_table(
        "workflow_steps",
        sa.Column("step_id",sa.Uuid(),primary_key=True),
        sa.Column("tenant_id",sa.Uuid(),sa.ForeignKey("tenants.tenant_id",ondelete="CASCADE"),nullable=False),
        sa.Column("run_id",sa.Uuid(),sa.ForeignKey("graph_runs.run_id",ondelete="CASCADE"),nullable=False),
        sa.Column("step_key",sa.String(240),nullable=False),
        sa.Column("idempotency_key",sa.String(320),nullable=False),
        sa.Column("status",sa.String(24),nullable=False),
        sa.Column("attempt_number",sa.Integer(),nullable=False,server_default="1"),
        sa.Column("timeout_seconds",sa.Float(),nullable=False),
        sa.Column("output_json",postgresql.JSONB(astext_type=sa.Text()),nullable=True),
        sa.Column("output_sha256",sa.String(64),nullable=True),
        sa.Column("error_code",sa.String(160),nullable=True),
        sa.Column("compensation_status",sa.String(24),nullable=False,server_default="none"),
        sa.Column("started_at",sa.DateTime(timezone=True),nullable=True),
        sa.Column("completed_at",sa.DateTime(timezone=True),nullable=True),
        sa.Column("updated_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.text("now()")),
        sa.UniqueConstraint("tenant_id","run_id","idempotency_key",name="uq_step_idempotency"),
        sa.CheckConstraint("status IN ('pending','running','completed','failed','cancelled','compensated')",name="ck_step_status"),
        sa.CheckConstraint("compensation_status IN ('none','required','running','completed','failed')",name="ck_compensation_status"),
        sa.CheckConstraint("attempt_number >= 1",name="ck_step_attempt"),
        sa.CheckConstraint("timeout_seconds > 0 AND timeout_seconds <= 3600",name="ck_step_timeout"),
    )
    op.create_table(
        "workflow_durability_events",
        sa.Column("event_id",sa.Uuid(),primary_key=True),
        sa.Column("tenant_id",sa.Uuid(),sa.ForeignKey("tenants.tenant_id",ondelete="CASCADE"),nullable=False),
        sa.Column("run_id",sa.Uuid(),sa.ForeignKey("graph_runs.run_id",ondelete="CASCADE"),nullable=False),
        sa.Column("sequence",sa.Integer(),nullable=False),
        sa.Column("event_type",sa.String(160),nullable=False),
        sa.Column("payload",postgresql.JSONB(astext_type=sa.Text()),nullable=False,server_default=sa.text("'{}'::jsonb")),
        sa.Column("occurred_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.text("now()")),
        sa.UniqueConstraint("tenant_id","run_id","sequence",name="uq_durability_event_sequence"),
        sa.CheckConstraint("sequence >= 1",name="ck_durability_event_sequence"),
    )
    op.create_index("ix_lease_stuck","workflow_leases",["tenant_id","expires_at","cancelled_at"])
    op.create_index("ix_lease_owner","workflow_leases",["tenant_id","owner_id","expires_at"])
    op.create_index("ix_step_status","workflow_steps",["tenant_id","run_id","status","updated_at"])
    op.create_index("ix_step_compensation","workflow_steps",["tenant_id","compensation_status","updated_at"])
    op.create_index("ix_durability_events","workflow_durability_events",["tenant_id","run_id","sequence"])
    for t in ("workflow_leases","workflow_steps","workflow_durability_events"): _rls(t)

    op.execute("""
    CREATE OR REPLACE FUNCTION validate_run_tenant() RETURNS trigger AS $$
    BEGIN
      IF NOT EXISTS (SELECT 1 FROM graph_runs r WHERE r.run_id=NEW.run_id AND r.tenant_id=NEW.tenant_id) THEN
        RAISE EXCEPTION 'workflow/run tenant mismatch';
      END IF;
      RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    CREATE TRIGGER trg_lease_run_tenant BEFORE INSERT OR UPDATE ON workflow_leases FOR EACH ROW EXECUTE FUNCTION validate_run_tenant();
    CREATE TRIGGER trg_step_run_tenant BEFORE INSERT OR UPDATE ON workflow_steps FOR EACH ROW EXECUTE FUNCTION validate_run_tenant();
    CREATE TRIGGER trg_event_run_tenant BEFORE INSERT ON workflow_durability_events FOR EACH ROW EXECUTE FUNCTION validate_run_tenant();
    """)
    op.execute("""
    CREATE OR REPLACE FUNCTION validate_step_transition() RETURNS trigger AS $$
    DECLARE ok boolean := false;
    BEGIN
      ok :=
        (OLD.status='running' AND NEW.status IN ('completed','failed','cancelled')) OR
        (OLD.status='failed' AND NEW.status IN ('running','compensated','failed')) OR
        (OLD.status='cancelled' AND NEW.status='running') OR
        (OLD.status=NEW.status);
      IF NOT ok THEN RAISE EXCEPTION 'invalid step transition % -> %', OLD.status, NEW.status; END IF;
      IF OLD.status='completed' AND NEW.status <> 'completed' THEN RAISE EXCEPTION 'completed idempotent step is terminal'; END IF;
      IF NEW.attempt_number < OLD.attempt_number OR NEW.attempt_number > OLD.attempt_number + 1 THEN RAISE EXCEPTION 'invalid attempt increment'; END IF;
      RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    CREATE TRIGGER trg_step_transition BEFORE UPDATE ON workflow_steps FOR EACH ROW EXECUTE FUNCTION validate_step_transition();
    """)
    op.execute("""
    CREATE OR REPLACE FUNCTION prevent_durability_event_mutation() RETURNS trigger AS $$
    BEGIN RAISE EXCEPTION 'durability events are append-only'; END;
    $$ LANGUAGE plpgsql;
    CREATE TRIGGER trg_durability_events_immutable BEFORE UPDATE OR DELETE ON workflow_durability_events FOR EACH ROW EXECUTE FUNCTION prevent_durability_event_mutation();
    """)


def downgrade()->None:
    op.execute("DROP TRIGGER IF EXISTS trg_durability_events_immutable ON workflow_durability_events")
    op.execute("DROP FUNCTION IF EXISTS prevent_durability_event_mutation()")
    op.execute("DROP TRIGGER IF EXISTS trg_step_transition ON workflow_steps")
    op.execute("DROP FUNCTION IF EXISTS validate_step_transition()")
    op.execute("DROP TRIGGER IF EXISTS trg_event_run_tenant ON workflow_durability_events")
    op.execute("DROP TRIGGER IF EXISTS trg_step_run_tenant ON workflow_steps")
    op.execute("DROP TRIGGER IF EXISTS trg_lease_run_tenant ON workflow_leases")
    op.execute("DROP FUNCTION IF EXISTS validate_run_tenant()")
    op.drop_table("workflow_durability_events")
    op.drop_table("workflow_steps")
    op.drop_table("workflow_leases")
