from uuid import UUID
from verideploy.multimodal.repository import IngestionRepository
from verideploy.multimodal.schemas import IngestionCommand, IngestionEvent, IngestionJob, IngestionStatus


class IngestionService:
    def __init__(self, repository: IngestionRepository) -> None: self.repository=repository
    def accept(self, command: IngestionCommand) -> tuple[IngestionJob, bool]: return self.repository.create_or_get(command)
    def get(self, tenant_id: UUID, job_id: UUID) -> IngestionJob | None: return self.repository.get(tenant_id, job_id)
    def events(self, tenant_id: UUID, job_id: UUID, *, after_sequence: int=0) -> list[IngestionEvent]: return self.repository.list_events(tenant_id, job_id, after_sequence=after_sequence)
    def initialize(self, tenant_id: UUID, job_id: UUID) -> tuple[IngestionJob, list[IngestionEvent]]:
        events=[]
        job,e=self.repository.transition_with_event(tenant_id, job_id, IngestionStatus.STORED, event_type="ingestion.object.stored", payload={"status":"STORED"}); events.append(e)
        job,e=self.repository.transition_with_event(tenant_id, job_id, IngestionStatus.PROCESSING, event_type="ingestion.processing.started", payload={"status":"PROCESSING","stage":"intake_validation"}); events.append(e)
        job,e=self.repository.transition_with_event(tenant_id, job_id, IngestionStatus.READY, event_type="ingestion.ready", payload={"status":"READY","next_stage":"modality_specific_processing"}); events.append(e)
        return job,events
