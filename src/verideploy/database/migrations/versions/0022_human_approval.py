"""Durable human approval.

Revision ID: 0022_milestone41_human_approval
Revises: 0021_milestone39_langgraph_state_reducers
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0022_milestone41_human_approval"
down_revision = "0021_milestone39_langgraph_state_reducers"
branch_labels = None
depends_on = None


def _rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {table}_tenant_isolation ON {table} "
        "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
        "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
    )


def upgrade() -> None:
    op.create_table(
        "approval_requests",
        sa.Column("approval_id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False),
        sa.Column("run_id", sa.Uuid(), sa.ForeignKey("graph_runs.run_id", ondelete="CASCADE"), nullable=False),
        sa.Column("investigation_id", sa.String(255), nullable=False),
        sa.Column("action_type", sa.String(160), nullable=False),
        sa.Column("action_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("risk", sa.String(20), nullable=False),
        sa.Column("risk_score", sa.Integer(), nullable=False),
        sa.Column("requested_by", sa.String(256), nullable=False),
        sa.Column("evidence_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("policy", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("reviewer_id", sa.String(256), nullable=True),
        sa.Column("delegated_to", sa.String(256), nullable=True),
        sa.Column("decision_comment", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_approval_idempotency"),
        sa.CheckConstraint("risk IN ('low','medium','high','critical')", name="ck_approval_risk"),
        sa.CheckConstraint("risk_score BETWEEN 0 AND 100", name="ck_approval_risk_score"),
        sa.CheckConstraint("status IN ('pending','in_review','changes_requested','approved','rejected','expired','cancelled')", name="ck_approval_status"),
        sa.CheckConstraint("version >= 1", name="ck_approval_version"),
        sa.CheckConstraint("expires_at >= created_at", name="ck_approval_expiry"),
    )
    op.create_table(
        "approval_events",
        sa.Column("event_id", sa.Uuid(), primary_key=True),
        sa.Column("approval_id", sa.Uuid(), sa.ForeignKey("approval_requests.approval_id", ondelete="CASCADE"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("actor_id", sa.String(256), nullable=False),
        sa.Column("actor_role", sa.String(120), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("previous_status", sa.String(32), nullable=True),
        sa.Column("new_status", sa.String(32), nullable=True),
        sa.Column("signed_payload_sha256", sa.String(64), nullable=False),
        sa.Column("signature", sa.String(64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("tenant_id", "approval_id", "sequence", name="uq_approval_event_sequence"),
        sa.CheckConstraint("sequence >= 1", name="ck_approval_event_sequence"),
    )
    op.create_index("ix_approval_queue", "approval_requests", ["tenant_id", "status", "risk_score", "expires_at"])
    op.create_index("ix_approval_run", "approval_requests", ["tenant_id", "run_id", "created_at"])
    op.create_index("ix_approval_delegated", "approval_requests", ["tenant_id", "delegated_to", "status"])
    op.create_index("ix_approval_events", "approval_events", ["tenant_id", "approval_id", "sequence"])
    _rls("approval_requests")
    _rls("approval_events")

    op.execute("""
    CREATE OR REPLACE FUNCTION prevent_approval_event_mutation() RETURNS trigger AS $$
    BEGIN RAISE EXCEPTION 'approval audit events are append-only'; END;
    $$ LANGUAGE plpgsql;
    CREATE TRIGGER trg_approval_events_immutable
    BEFORE UPDATE OR DELETE ON approval_events
    FOR EACH ROW EXECUTE FUNCTION prevent_approval_event_mutation();
    """)
    op.execute("""
    CREATE OR REPLACE FUNCTION validate_approval_tenant() RETURNS trigger AS $$
    BEGIN
      IF NOT EXISTS (SELECT 1 FROM graph_runs r WHERE r.run_id=NEW.run_id AND r.tenant_id=NEW.tenant_id) THEN
        RAISE EXCEPTION 'approval/run tenant mismatch';
      END IF;
      RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    CREATE TRIGGER trg_approval_run_tenant
    BEFORE INSERT OR UPDATE ON approval_requests
    FOR EACH ROW EXECUTE FUNCTION validate_approval_tenant();
    """)
    op.execute("""
    CREATE OR REPLACE FUNCTION validate_request_transition() RETURNS trigger AS $$
    DECLARE ok boolean := false;
    BEGIN
      IF NEW.version <> OLD.version + 1 THEN
        RAISE EXCEPTION 'approval version must increment exactly once';
      END IF;
      ok :=
        (OLD.status='pending' AND NEW.status IN ('in_review','changes_requested','approved','rejected','expired','cancelled')) OR
        (OLD.status='in_review' AND NEW.status IN ('in_review','changes_requested','approved','rejected','expired','cancelled')) OR
        (OLD.status='changes_requested' AND NEW.status IN ('in_review','changes_requested','approved','rejected','expired','cancelled'));
      IF NOT ok THEN RAISE EXCEPTION 'invalid approval lifecycle transition % -> %', OLD.status, NEW.status; END IF;
      IF NEW.status IN ('approved','rejected','changes_requested') AND NEW.reviewer_id IS NULL THEN
        RAISE EXCEPTION 'reviewer identity required for reviewer decision';
      END IF;
      RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    CREATE TRIGGER trg_request_transition
    BEFORE UPDATE ON approval_requests
    FOR EACH ROW EXECUTE FUNCTION validate_request_transition();
    """)
    op.execute("""
    CREATE OR REPLACE FUNCTION require_signed_transition_event() RETURNS trigger AS $$
    BEGIN
      IF NOT EXISTS (
        SELECT 1 FROM approval_events e
        WHERE e.tenant_id=NEW.tenant_id AND e.approval_id=NEW.approval_id
          AND e.sequence=NEW.version AND e.new_status=NEW.status
          AND length(e.signature)=64 AND length(e.signed_payload_sha256)=64
      ) THEN
        RAISE EXCEPTION 'approval transition requires matching signed audit event';
      END IF;
      RETURN NULL;
    END;
    $$ LANGUAGE plpgsql;
    CREATE CONSTRAINT TRIGGER trg_signed_transition_event
    AFTER UPDATE ON approval_requests
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION require_signed_transition_event();
    """)

    op.execute("""
    CREATE OR REPLACE FUNCTION validate_event_tenant() RETURNS trigger AS $$
    BEGIN
      IF NOT EXISTS (SELECT 1 FROM approval_requests a WHERE a.approval_id=NEW.approval_id AND a.tenant_id=NEW.tenant_id) THEN
        RAISE EXCEPTION 'approval event tenant mismatch';
      END IF;
      RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    CREATE TRIGGER trg_event_tenant
    BEFORE INSERT ON approval_events
    FOR EACH ROW EXECUTE FUNCTION validate_event_tenant();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_signed_transition_event ON approval_requests")
    op.execute("DROP FUNCTION IF EXISTS require_signed_transition_event()")
    op.execute("DROP TRIGGER IF EXISTS trg_request_transition ON approval_requests")
    op.execute("DROP FUNCTION IF EXISTS validate_request_transition()")
    op.execute("DROP TRIGGER IF EXISTS trg_event_tenant ON approval_events")
    op.execute("DROP FUNCTION IF EXISTS validate_event_tenant()")
    op.execute("DROP TRIGGER IF EXISTS trg_approval_run_tenant ON approval_requests")
    op.execute("DROP FUNCTION IF EXISTS validate_approval_tenant()")
    op.execute("DROP TRIGGER IF EXISTS trg_approval_events_immutable ON approval_events")
    op.execute("DROP FUNCTION IF EXISTS prevent_approval_event_mutation()")
    op.drop_table("approval_events")
    op.drop_table("approval_requests")
