from __future__ import annotations

import asyncio
import os

from verideploy.config import get_settings
from verideploy.observability.telemetry import configure_telemetry
from verideploy.investigations.repository import SqlAlchemyInvestigationRepository
from verideploy.investigations.service import InvestigationService
from workers.investigation.investigation_worker import run_kafka_worker
from services.ai.agents import get_incident_agent_bundle
from verideploy.graphs.factory import create_production_graph_runtime


async def _main() -> None:
    settings = get_settings()
    configure_telemetry(settings, service_name="verideploy-investigation-worker")
    database_url = os.getenv("INVESTIGATION_DATABASE_URL", settings.database_url)
    repository = SqlAlchemyInvestigationRepository(database_url, create_schema=settings.app_env in {"development", "test"})
    graphs = await create_production_graph_runtime(settings, incident_agents=get_incident_agent_bundle())
    try:
        await run_kafka_worker(InvestigationService(repository), graphs.runtime, settings.kafka_brokers)
    finally:
        await graphs.close()


def main() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    main()
