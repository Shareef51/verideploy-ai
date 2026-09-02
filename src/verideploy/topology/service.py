from __future__ import annotations

from uuid import UUID

from verideploy.topology.repository import TopologyRepository
from verideploy.topology.schemas import TopologySnapshot
from verideploy.topology.validation import validate_topology


class TopologyService:
    def __init__(self, repository: TopologyRepository) -> None: self.repository = repository
    def seed(self, snapshot: TopologySnapshot) -> TopologySnapshot:
        report = validate_topology(snapshot)
        if not report.valid: raise ValueError("invalid topology: " + "; ".join(report.errors))
        self.repository.persist(snapshot)
        return snapshot
    def get(self, *, tenant_id: UUID, company_slug: str = "nexuspay") -> TopologySnapshot | None:
        return self.repository.get_snapshot(tenant_id=tenant_id, company_slug=company_slug)
