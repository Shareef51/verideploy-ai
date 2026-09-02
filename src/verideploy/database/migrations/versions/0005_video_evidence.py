"""Video evidence persistence.

Revision ID: 0005_milestone17_video_evidence
Revises: 0004_milestone16_audio_transcription
"""
from alembic import op
import sqlalchemy as sa

revision = "0005_milestone17_video_evidence"
down_revision = "0004_milestone16_audio_transcription"
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
        "video_evidence_jobs",
        sa.Column("video_job_id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False),
        sa.Column("ingestion_job_id", sa.Uuid(), nullable=False),
        sa.Column("correlation_id", sa.Uuid(), nullable=False),
        sa.Column("video_sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("has_audio", sa.String(5), nullable=True),
        sa.Column("transcription_id", sa.Uuid(), nullable=True),
        sa.Column("frame_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("timeline_event_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("degradation_reasons_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("error_code", sa.String(80), nullable=True),
        sa.Column("error_message", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("tenant_id", "ingestion_job_id", name="uq_video_evidence_identity"),
    )
    op.create_table(
        "video_keyframes",
        sa.Column("frame_id", sa.Uuid(), primary_key=True),
        sa.Column("video_job_id", sa.Uuid(), sa.ForeignKey("video_evidence_jobs.video_job_id", ondelete="CASCADE"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("timestamp_seconds", sa.Float(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False), sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("selection_reason", sa.String(120), nullable=False),
        sa.Column("object_ref", sa.String(1024), nullable=False),
        sa.Column("evidence_id", sa.String(40), nullable=False),
        sa.Column("observation_json", sa.Text(), nullable=False),
        sa.CheckConstraint("timestamp_seconds >= 0", name="ck_video_frame_timestamp"),
        sa.UniqueConstraint("tenant_id", "video_job_id", "sequence_number", name="uq_video_frame_sequence"),
        sa.UniqueConstraint("tenant_id", "evidence_id", name="uq_video_frame_evidence"),
    )
    op.create_table(
        "video_timeline_events",
        sa.Column("event_id", sa.Uuid(), primary_key=True),
        sa.Column("video_job_id", sa.Uuid(), sa.ForeignKey("video_evidence_jobs.video_job_id", ondelete="CASCADE"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("timestamp_seconds", sa.Float(), nullable=False),
        sa.Column("kind", sa.String(50), nullable=False),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("evidence_ids_json", sa.Text(), nullable=False),
        sa.Column("frame_id", sa.Uuid(), nullable=True),
        sa.Column("transcript_segment_id", sa.Uuid(), nullable=True),
        sa.Column("alignment_delta_seconds", sa.Float(), nullable=True),
        sa.CheckConstraint("timestamp_seconds >= 0", name="ck_video_timeline_timestamp"),
        sa.UniqueConstraint("tenant_id", "video_job_id", "sequence_number", name="uq_video_timeline_sequence"),
    )
    op.create_index("ix_video_jobs_tenant_status", "video_evidence_jobs", ["tenant_id", "status"])
    op.create_index("ix_video_frames_tenant_job_time", "video_keyframes", ["tenant_id", "video_job_id", "timestamp_seconds"])
    op.create_index("ix_video_timeline_tenant_job_time", "video_timeline_events", ["tenant_id", "video_job_id", "timestamp_seconds"])
    for table in ("video_evidence_jobs", "video_keyframes", "video_timeline_events"):
        _tenant_policy(table)


def downgrade() -> None:
    op.drop_table("video_timeline_events")
    op.drop_table("video_keyframes")
    op.drop_table("video_evidence_jobs")
