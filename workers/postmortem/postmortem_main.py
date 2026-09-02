from __future__ import annotations

import asyncio
import os

from verideploy.config import get_settings
from verideploy.observability.telemetry import configure_telemetry
from verideploy.investigations.repository import SqlAlchemyInvestigationRepository
from verideploy.investigations.service import InvestigationService
from verideploy.postmortems.repository import SqlAlchemyPostmortemRepository
from verideploy.postmortems.service import PostmortemService
from workers.postmortem.postmortem_worker import run_kafka_worker


def main() -> None:
    settings = get_settings()
    configure_telemetry(settings, service_name="verideploy-postmortem-worker")
    database_url = os.getenv("POSTMORTEM_DATABASE_URL") or os.getenv("INVESTIGATION_DATABASE_URL", settings.database_url)
    investigations = InvestigationService(SqlAlchemyInvestigationRepository(database_url, create_schema=settings.app_env in {"development", "test"}))
    postmortems = PostmortemService(SqlAlchemyPostmortemRepository(database_url, create_schema=settings.app_env in {"development", "test"}), investigations)
    asyncio.run(run_kafka_worker(postmortems, settings.kafka_brokers))


if __name__ == "__main__":
    main()
