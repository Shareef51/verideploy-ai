from pathlib import Path


def test_langgraph_runtime_migration_has_run_event_tables_and_forced_rls():
    text = Path("src/verideploy/database/migrations/versions/0006_langgraph_runtime.py").read_text()
    assert 'revision = "0006_milestone18_langgraph_runtime"' in text
    assert 'down_revision = "0005_milestone17_video_evidence"' in text
    assert '"graph_runs"' in text
    assert '"graph_runtime_events"' in text
    assert "ENABLE ROW LEVEL SECURITY" in text
    assert "FORCE ROW LEVEL SECURITY" in text
    assert "uq_graph_event_sequence" in text
