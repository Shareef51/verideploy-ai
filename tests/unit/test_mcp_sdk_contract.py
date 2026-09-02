from pathlib import Path


def test_project_declares_current_mcp_v2_dependency():
    text = Path("pyproject.toml").read_text()
    assert '"mcp>=2,<3"' in text


def test_four_mcp_server_builders_exist():
    base = Path("src/verideploy/mcp/servers")
    for name in ("github.py", "monitoring.py", "knowledge.py", "incident.py"):
        assert (base / name).exists()
