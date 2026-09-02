from pathlib import Path

import yaml


def test_database_dependent_services_wait_for_alembic_migration_job() -> None:
    compose = yaml.safe_load(Path("docker-compose.yml").read_text())
    services = compose["services"]
    assert services["db-migrate"]["command"] == ["alembic", "upgrade", "head"]
    assert services["db-migrate"]["depends_on"]["postgres"]["condition"] == "service_healthy"
    for name in ["ai-service", "release-risk-worker", "ingestion-worker", "investigation-worker", "postmortem-worker"]:
        assert services[name]["depends_on"]["db-migrate"]["condition"] == "service_completed_successfully"
