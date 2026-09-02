from pathlib import Path

from verideploy.config import Settings


def test_config_has_sync_durability_and_timeout():
    settings = Settings(app_env="test")
    assert settings.langgraph_durability == "sync"
    assert settings.langgraph_default_timeout_seconds == 300


def test_declares_real_langgraph_runtime_dependencies():
    text = Path("pyproject.toml").read_text()
    assert '"langgraph>=0.6,<2"' in text
    assert '"langgraph-checkpoint-postgres>=2,<4"' in text


def test_factory_requires_postgres_source_contract():
    source = Path("src/verideploy/graphs/factory.py").read_text()
    assert "create_postgres_checkpointer" in source
    assert "SqlAlchemyGraphRuntimeRepository" in source
    assert "production LangGraph runtime requires PostgreSQL" in source
