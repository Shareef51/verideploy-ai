from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID

from sqlalchemy import text

from verideploy.database.session import DatabaseManager
from verideploy.topology.schemas import TopologySnapshot


class TopologyRepository(ABC):
    @abstractmethod
    def persist(self, snapshot: TopologySnapshot) -> None: ...
    @abstractmethod
    def get_snapshot(self, *, tenant_id: UUID, company_slug: str) -> TopologySnapshot | None: ...


class InMemoryTopologyRepository(TopologyRepository):
    def __init__(self) -> None: self._snapshots: dict[tuple[UUID, str], TopologySnapshot] = {}
    def persist(self, snapshot: TopologySnapshot) -> None: self._snapshots[(snapshot.company.tenant_id, snapshot.company.slug)] = snapshot
    def get_snapshot(self, *, tenant_id: UUID, company_slug: str) -> TopologySnapshot | None: return self._snapshots.get((tenant_id, company_slug))


class PostgresTopologyRepository(TopologyRepository):
    def __init__(self, db: DatabaseManager) -> None:
        if db.engine.dialect.name != "postgresql": raise ValueError("PostgresTopologyRepository requires PostgreSQL")
        self.db = db

    def persist(self, snapshot: TopologySnapshot) -> None:
        tenant_id = snapshot.company.tenant_id
        with self.db.engine.begin() as conn:
            conn.execute(text("INSERT INTO tenants (tenant_id,slug,display_name) VALUES (:id,:slug,:name) ON CONFLICT (tenant_id) DO UPDATE SET display_name=EXCLUDED.display_name"), {"id":str(tenant_id),"slug":snapshot.company.slug,"name":snapshot.company.name})
        with self.db.tenant_session(tenant_id, statement_timeout_ms=30_000) as session:
            session.execute(text("""
                INSERT INTO topology_companies (company_id,tenant_id,name,slug,seed_version,seed_sha256,generated_at)
                VALUES (:company_id,:tenant_id,:name,:slug,:seed_version,:seed_sha256,:generated_at)
                ON CONFLICT (tenant_id,slug) DO UPDATE SET name=EXCLUDED.name,seed_version=EXCLUDED.seed_version,seed_sha256=EXCLUDED.seed_sha256,generated_at=EXCLUDED.generated_at
            """), {"company_id":str(snapshot.company.company_id),"tenant_id":str(tenant_id),"name":snapshot.company.name,"slug":snapshot.company.slug,"seed_version":snapshot.seed_version,"seed_sha256":snapshot.seed_sha256,"generated_at":snapshot.generated_at})
            for row in snapshot.teams:
                session.execute(text("""INSERT INTO topology_teams (team_id,tenant_id,company_id,name,slug,mission) VALUES (:team_id,:tenant_id,:company_id,:name,:slug,:mission) ON CONFLICT (team_id) DO UPDATE SET name=EXCLUDED.name,slug=EXCLUDED.slug,mission=EXCLUDED.mission"""), row.model_dump(mode="json"))
            for row in snapshot.owners:
                session.execute(text("""INSERT INTO topology_owners (owner_id,tenant_id,team_id,display_name,role,oncall_alias) VALUES (:owner_id,:tenant_id,:team_id,:display_name,:role,:oncall_alias) ON CONFLICT (owner_id) DO UPDATE SET display_name=EXCLUDED.display_name,role=EXCLUDED.role,oncall_alias=EXCLUDED.oncall_alias"""), row.model_dump(mode="json"))
            for row in snapshot.environments:
                payload=row.model_dump(mode="json"); payload["criticality"]=row.criticality.value
                session.execute(text("""INSERT INTO topology_environments (environment_id,tenant_id,name,region,criticality) VALUES (:environment_id,:tenant_id,:name,:region,:criticality) ON CONFLICT (environment_id) DO UPDATE SET region=EXCLUDED.region,criticality=EXCLUDED.criticality"""), payload)
            for row in snapshot.services:
                payload=row.model_dump(mode="json"); payload["tier"]=row.tier.value
                session.execute(text("""INSERT INTO topology_services (service_id,tenant_id,team_id,name,slug,domain,tier,runtime,repository,description) VALUES (:service_id,:tenant_id,:team_id,:name,:slug,:domain,:tier,:runtime,:repository,:description) ON CONFLICT (service_id) DO UPDATE SET team_id=EXCLUDED.team_id,name=EXCLUDED.name,slug=EXCLUDED.slug,domain=EXCLUDED.domain,tier=EXCLUDED.tier,runtime=EXCLUDED.runtime,repository=EXCLUDED.repository,description=EXCLUDED.description"""), payload)
            for row in snapshot.dependencies:
                payload=row.model_dump(mode="json"); payload.update(kind=row.kind.value,criticality=row.criticality.value)
                session.execute(text("""INSERT INTO topology_dependencies (dependency_id,tenant_id,source_service_id,target_service_id,kind,criticality,description) VALUES (:dependency_id,:tenant_id,:source_service_id,:target_service_id,:kind,:criticality,:description) ON CONFLICT (dependency_id) DO UPDATE SET kind=EXCLUDED.kind,criticality=EXCLUDED.criticality,description=EXCLUDED.description"""), payload)
            for row in snapshot.slos:
                payload=row.model_dump(mode="json"); payload["metric"]=row.metric.value
                session.execute(text("""INSERT INTO topology_slos (slo_id,tenant_id,service_id,environment_id,metric,target,window_days) VALUES (:slo_id,:tenant_id,:service_id,:environment_id,:metric,:target,:window_days) ON CONFLICT (slo_id) DO UPDATE SET target=EXCLUDED.target,window_days=EXCLUDED.window_days"""), payload)
            for row in snapshot.deployments:
                session.execute(text("""INSERT INTO topology_deployments (deployment_id,tenant_id,service_id,environment_id,version,commit_sha,deployed_at,cluster,namespace,replicas) VALUES (:deployment_id,:tenant_id,:service_id,:environment_id,:version,:commit_sha,:deployed_at,:cluster,:namespace,:replicas) ON CONFLICT (deployment_id) DO UPDATE SET version=EXCLUDED.version,commit_sha=EXCLUDED.commit_sha,deployed_at=EXCLUDED.deployed_at,cluster=EXCLUDED.cluster,namespace=EXCLUDED.namespace,replicas=EXCLUDED.replicas"""), row.model_dump(mode="json"))
            session.commit()

    def get_snapshot(self, *, tenant_id: UUID, company_slug: str) -> TopologySnapshot | None:
        with self.db.tenant_session(tenant_id) as session:
            company = session.execute(text("SELECT * FROM topology_companies WHERE tenant_id=:tenant_id AND slug=:slug"), {"tenant_id":str(tenant_id),"slug":company_slug}).mappings().first()
            if company is None: return None
            def rows(table: str, order: str): return [dict(row) for row in session.execute(text(f"SELECT * FROM {table} WHERE tenant_id=:tenant_id ORDER BY {order}"), {"tenant_id":str(tenant_id)}).mappings()]
            payload={
                "schema_version":"1.0","seed_version":company["seed_version"],"generated_at":company["generated_at"],"seed_sha256":company["seed_sha256"],
                "company":{"company_id":company["company_id"],"tenant_id":company["tenant_id"],"name":company["name"],"slug":company["slug"]},
                "teams":rows("topology_teams","slug"),"owners":rows("topology_owners","display_name"),"environments":rows("topology_environments","name"),
                "services":rows("topology_services","slug"),"dependencies":rows("topology_dependencies","dependency_id"),"slos":rows("topology_slos","slo_id"),"deployments":rows("topology_deployments","deployment_id"),
            }
            return TopologySnapshot.model_validate(payload)
