from pathlib import Path


def test_migration_has_transcript_tables_rls_and_idempotent_constraints():
    text = Path("src/verideploy/database/migrations/versions/0004_audio_transcription.py").read_text()
    assert '"audio_transcriptions"' in text
    assert '"audio_transcript_segments"' in text
    assert "ENABLE ROW LEVEL SECURITY" in text
    assert "FORCE ROW LEVEL SECURITY" in text
    assert "uq_audio_transcription_identity" in text
    assert "uq_audio_segment_sequence" in text
    assert "raw_text_sha256" in text
    assert "evidence_id" in text
