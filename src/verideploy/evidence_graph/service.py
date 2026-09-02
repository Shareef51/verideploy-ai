from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from verideploy.evidence.repository import EvidenceRepository
from verideploy.evidence_graph.repository import EvidenceGraphRepository, GraphConflictError, GraphNotFoundError
from verideploy.evidence_graph.schemas import GraphEdge, GraphEdgeCreate, GraphEntity, GraphEntityCreate, GraphPath, GraphSnapshot, edge_id_for, entity_id_for, snapshot_sha256


class EvidenceGraphService:
    def __init__(self, repository: EvidenceGraphRepository, evidence_repository: EvidenceRepository | None = None) -> None:
        self.repository=repository; self.evidence_repository=evidence_repository

    @staticmethod
    def _now() -> datetime: return datetime.now(timezone.utc)

    def put_entity(self, request: GraphEntityCreate) -> GraphEntity:
        if request.evidence_record_id is not None:
            if self.evidence_repository is None or self.evidence_repository.get_record(tenant_id=request.tenant_id,record_id=request.evidence_record_id) is None:
                raise GraphNotFoundError("referenced immutable evidence record not found in tenant scope")
        row=GraphEntity(entity_id=entity_id_for(request.tenant_id,request.entity_type,request.natural_key),tenant_id=request.tenant_id,entity_type=request.entity_type,natural_key=request.natural_key,label=request.label,reference_uri=request.reference_uri,evidence_record_id=request.evidence_record_id,attributes=request.attributes,observed_at=request.observed_at,created_at=request.observed_at or self._now())
        return self.repository.upsert_entity(row)

    def put_edge(self, request: GraphEdgeCreate) -> GraphEdge:
        source=self.repository.get_entity(tenant_id=request.tenant_id,entity_id=request.source_entity_id); target=self.repository.get_entity(tenant_id=request.tenant_id,entity_id=request.target_entity_id)
        if source is None or target is None: raise GraphNotFoundError("graph edge endpoints not found in tenant scope")
        row=GraphEdge(edge_id=edge_id_for(request.tenant_id,request.source_entity_id,request.relationship,request.target_entity_id,request.occurred_at),tenant_id=request.tenant_id,source_entity_id=request.source_entity_id,target_entity_id=request.target_entity_id,relationship=request.relationship,confidence=request.confidence,occurred_at=request.occurred_at,valid_from=request.valid_from,valid_to=request.valid_to,attributes=request.attributes,created_at=request.occurred_at or self._now())
        return self.repository.upsert_edge(row)

    def path(self, *, tenant_id: UUID, source_entity_id: UUID, target_entity_id: UUID, max_depth: int = 6) -> GraphPath:
        if max_depth < 1 or max_depth > 12: raise GraphConflictError("max_depth must be between 1 and 12")
        result=self.repository.shortest_path(tenant_id=tenant_id,source_entity_id=source_entity_id,target_entity_id=target_entity_id,max_depth=max_depth)
        if result is None: raise GraphNotFoundError("no graph path found")
        return GraphPath(entities=result[0],edges=result[1])

    def snapshot(self, *, tenant_id: UUID) -> GraphSnapshot:
        entities=self.repository.list_entities(tenant_id=tenant_id); edges=self.repository.list_edges(tenant_id=tenant_id)
        return GraphSnapshot(tenant_id=tenant_id,snapshot_sha256=snapshot_sha256(entities,edges),entities=entities,edges=edges)
