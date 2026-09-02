import asyncio
from verideploy.config import get_settings
from verideploy.observability.telemetry import configure_telemetry
from verideploy.multimodal.repository import SqlAlchemyIngestionRepository
from verideploy.multimodal.service import IngestionService
from workers.ingestion.ingestion_worker import run_kafka_worker

def main() -> None:
    s=get_settings(); configure_telemetry(s, service_name="verideploy-ingestion-worker"); repo=SqlAlchemyIngestionRepository(s.database_url, create_schema=True); asyncio.run(run_kafka_worker(IngestionService(repo), s.kafka_brokers))
if __name__ == "__main__": main()
