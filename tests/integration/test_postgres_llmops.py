import os,pytest
from pathlib import Path
pytestmark=pytest.mark.skipif(not os.getenv("TEST_POSTGRES_URL"),reason="TEST_POSTGRES_URL required")
def test_postgres_gate_contract():
 s=Path("src/verideploy/database/migrations/versions/0025_llmops_data_platform.py").read_text(); assert "FORCE ROW LEVEL SECURITY" in s and "app.retention_purge" in s and "append-only" in s
