from __future__ import annotations
from dataclasses import dataclass
from uuid import UUID
from verideploy.rag.visual_retrieval.service import VisualDocumentService

@dataclass(frozen=True)
class VisualIndexCommand:
    tenant_id: UUID
    document_id: UUID
    source_key: str
    title: str
    pdf_bytes: bytes

class VisualIndexWorker:
    """Transport-independent Visual Document Retrieval worker. Object-store transport supplies authorized PDF bytes."""
    def __init__(self, service: VisualDocumentService) -> None: self.service=service
    def handle(self, command: VisualIndexCommand) -> dict[str, object]:
        pages,indexes=self.service.index_pdf(tenant_id=command.tenant_id,document_id=command.document_id,source_key=command.source_key,title=command.title,pdf_bytes=command.pdf_bytes)
        return {"document_id":str(command.document_id),"pages_rendered":len(pages),"pages_indexed":len(indexes),"backend":self.service.adapter.backend.value,"model_name":self.service.adapter.model_name}
