from pathlib import Path


def test_migration_contract():
    text = Path("src/verideploy/database/migrations/versions/0005_video_evidence.py").read_text()
    assert 'revision = "0005_milestone17_video_evidence"' in text
    assert 'down_revision = "0004_milestone16_audio_transcription"' in text
    for table in ("video_evidence_jobs", "video_keyframes", "video_timeline_events"):
        assert f'"{table}"' in text
    assert "ENABLE ROW LEVEL SECURITY" in text
    assert "FORCE ROW LEVEL SECURITY" in text
    assert "tenant_isolation" in text
