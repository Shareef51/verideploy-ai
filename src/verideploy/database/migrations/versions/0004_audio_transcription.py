"""Audio transcription persistence.

Revision ID: 0004_milestone16_audio_transcription
Revises: 0003_milestone14_visual_document_retrieval
"""
from alembic import op
import sqlalchemy as sa

revision = "0004_milestone16_audio_transcription"
down_revision = "0003_milestone14_visual_document_retrieval"
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
        "audio_transcriptions",
        sa.Column("transcription_id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False),
        sa.Column("ingestion_job_id", sa.Uuid(), nullable=False),
        sa.Column("correlation_id", sa.Uuid(), nullable=False),
        sa.Column("model", sa.String(200), nullable=False),
        sa.Column("audio_sha256", sa.String(64), nullable=False),
        sa.Column("detected_mime_type", sa.String(40), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("language", sa.String(20), nullable=True),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("provider_request_id", sa.String(255), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_code", sa.String(80), nullable=True),
        sa.Column("error_message", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("tenant_id", "ingestion_job_id", "model", name="uq_audio_transcription_identity"),
    )
    op.create_table(
        "audio_transcript_segments",
        sa.Column("segment_id", sa.Uuid(), primary_key=True),
        sa.Column("transcription_id", sa.Uuid(), sa.ForeignKey("audio_transcriptions.transcription_id", ondelete="CASCADE"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("start_seconds", sa.Float(), nullable=False),
        sa.Column("end_seconds", sa.Float(), nullable=False),
        sa.Column("speaker", sa.String(120), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("raw_text_sha256", sa.String(64), nullable=False),
        sa.Column("evidence_id", sa.String(40), nullable=False),
        sa.CheckConstraint("start_seconds >= 0", name="ck_audio_segment_start"),
        sa.CheckConstraint("end_seconds > start_seconds", name="ck_audio_segment_time"),
        sa.UniqueConstraint("tenant_id", "transcription_id", "sequence_number", name="uq_audio_segment_sequence"),
        sa.UniqueConstraint("tenant_id", "evidence_id", name="uq_audio_segment_evidence"),
    )
    op.create_index("ix_audio_transcriptions_tenant_status", "audio_transcriptions", ["tenant_id", "status"])
    op.create_index("ix_audio_segments_tenant_transcription", "audio_transcript_segments", ["tenant_id", "transcription_id", "sequence_number"])
    _tenant_policy("audio_transcriptions")
    _tenant_policy("audio_transcript_segments")


def downgrade() -> None:
    op.drop_table("audio_transcript_segments")
    op.drop_table("audio_transcriptions")
