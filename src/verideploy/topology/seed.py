from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from uuid import UUID, uuid5

from verideploy.topology.schemas import (
    Criticality, DependencyKind, ServiceTier, SLOMetric, TopologyCompany, TopologyDependency,
    TopologyDeployment, TopologyEnvironment, TopologyOwner, TopologyService, TopologySLO,
    TopologySnapshot, TopologyTeam,
)

NAMESPACE = UUID("ab5a3e91-5100-5f3b-a6a6-28d2502f9ee0")
TENANT_ID = UUID("11111111-1111-4111-8111-111111111111")
GENERATED_AT = datetime(2026, 8, 17, 18, 0, tzinfo=timezone.utc)
SEED_VERSION = "nexuspay-v1"


def _id(kind: str, slug: str) -> UUID:
    return uuid5(NAMESPACE, f"{kind}:{slug}")


def _commit(slug: str, env: str) -> str:
    return hashlib.sha1(f"nexuspay:{slug}:{env}:".encode()).hexdigest()


def _payload_without_digest(snapshot: dict) -> str:
    clone = dict(snapshot)
    clone["seed_sha256"] = ""
    return json.dumps(clone, sort_keys=True, separators=(",", ":"), default=str)


def build_nexuspay_topology() -> TopologySnapshot:
    company_id = _id("company", "nexuspay")
    company = TopologyCompany(company_id=company_id, tenant_id=TENANT_ID, name="NexusPay", slug="nexuspay")

    team_specs = [
        ("edge-platform", "Edge Platform", "Own ingress, identity boundaries, and shared edge reliability."),
        ("commerce", "Commerce", "Own checkout, pricing, and inventory orchestration."),
        ("payments-risk", "Payments & Risk", "Own payment authorization, fraud controls, and money movement."),
        ("ledger-finance", "Ledger & Finance", "Own immutable ledger processing and financial consistency."),
        ("developer-platform", "Developer Platform", "Own telemetry, delivery foundations, and operational tooling."),
    ]
    teams = [TopologyTeam(team_id=_id("team", slug), tenant_id=TENANT_ID, company_id=company_id, name=name, slug=slug, mission=mission) for slug, name, mission in team_specs]
    team_ids = {team.slug: team.team_id for team in teams}

    owner_specs = [
        ("aisha-rahman", "Aisha Rahman", "edge-platform", "Staff Platform Engineer"),
        ("marcus-lee", "Marcus Lee", "commerce", "Engineering Manager"),
        ("priya-nair", "Priya Nair", "payments-risk", "Staff Payments Engineer"),
        ("daniel-okafor", "Daniel Okafor", "ledger-finance", "Principal Engineer"),
        ("sofia-martinez", "Sofia Martinez", "developer-platform", "SRE Lead"),
    ]
    owners = [TopologyOwner(owner_id=_id("owner", slug), tenant_id=TENANT_ID, team_id=team_ids[team], display_name=name, role=role, oncall_alias=f"{team}-oncall") for slug, name, team, role in owner_specs]

    env_specs = [
        ("development", "eu-west-1", Criticality.LOW),
        ("staging", "eu-west-1", Criticality.MEDIUM),
        ("production", "eu-west-1", Criticality.CRITICAL),
    ]
    environments = [TopologyEnvironment(environment_id=_id("environment", name), tenant_id=TENANT_ID, name=name, region=region, criticality=criticality) for name, region, criticality in env_specs]
    env_ids = {env.name: env.environment_id for env in environments}

    service_specs = [
        ("api-gateway", "API Gateway", "edge-platform", "edge", ServiceTier.TIER_0, "Node.js", "nexuspay/api-gateway", "Public ingress, request routing, authentication handoff, and correlation IDs."),
        ("identity-service", "Identity Service", "edge-platform", "identity", ServiceTier.TIER_0, "Java", "nexuspay/identity-service", "Customer and service identity verification and token policy."),
        ("checkout-api", "Checkout API", "commerce", "checkout", ServiceTier.TIER_0, "Python", "nexuspay/checkout-api", "Checkout orchestration across price, inventory, payment, and fraud decisions."),
        ("pricing-service", "Pricing Service", "commerce", "pricing", ServiceTier.TIER_1, "Go", "nexuspay/pricing-service", "Authoritative pricing, tax, discount, and quote calculations."),
        ("inventory-service", "Inventory Service", "commerce", "inventory", ServiceTier.TIER_1, "Java", "nexuspay/inventory-service", "Reservation and inventory availability for checkout."),
        ("payment-orchestrator", "Payment Orchestrator", "payments-risk", "payments", ServiceTier.TIER_0, "Kotlin", "nexuspay/payment-orchestrator", "Payment authorization routing, retries, and provider abstraction."),
        ("fraud-engine", "Fraud Engine", "payments-risk", "risk", ServiceTier.TIER_0, "Python", "nexuspay/fraud-engine", "Real-time transaction risk features and policy decisions."),
        ("ledger-service", "Ledger Service", "ledger-finance", "ledger", ServiceTier.TIER_0, "Java", "nexuspay/ledger-service", "Double-entry ledger posting and financial consistency."),
        ("notification-service", "Notification Service", "commerce", "communications", ServiceTier.TIER_2, "Node.js", "nexuspay/notification-service", "Customer email and push event delivery."),
        ("telemetry-gateway", "Telemetry Gateway", "developer-platform", "observability", ServiceTier.TIER_1, "Go", "nexuspay/telemetry-gateway", "OpenTelemetry ingest, routing, sampling, and export."),
    ]
    services = [TopologyService(service_id=_id("service", slug), tenant_id=TENANT_ID, team_id=team_ids[team], name=name, slug=slug, domain=domain, tier=tier, runtime=runtime, repository=repo, description=description) for slug, name, team, domain, tier, runtime, repo, description in service_specs]
    service_ids = {service.slug: service.service_id for service in services}

    dep_specs = [
        ("api-gateway", "identity-service", DependencyKind.SYNC_HTTP, Criticality.CRITICAL, "Authenticate customer and service requests."),
        ("api-gateway", "checkout-api", DependencyKind.SYNC_HTTP, Criticality.CRITICAL, "Route checkout traffic."),
        ("checkout-api", "pricing-service", DependencyKind.SYNC_HTTP, Criticality.HIGH, "Resolve authoritative checkout pricing."),
        ("checkout-api", "inventory-service", DependencyKind.SYNC_HTTP, Criticality.HIGH, "Reserve purchasable inventory."),
        ("checkout-api", "payment-orchestrator", DependencyKind.SYNC_HTTP, Criticality.CRITICAL, "Authorize payment before order completion."),
        ("checkout-api", "fraud-engine", DependencyKind.SYNC_HTTP, Criticality.CRITICAL, "Request transaction risk decision."),
        ("payment-orchestrator", "fraud-engine", DependencyKind.SYNC_HTTP, Criticality.HIGH, "Re-check risk for payment retry/provider context."),
        ("payment-orchestrator", "ledger-service", DependencyKind.ASYNC_EVENT, Criticality.CRITICAL, "Publish authorized payment events for posting."),
        ("ledger-service", "notification-service", DependencyKind.ASYNC_EVENT, Criticality.MEDIUM, "Emit settlement/customer notification events."),
        ("api-gateway", "telemetry-gateway", DependencyKind.TELEMETRY, Criticality.MEDIUM, "Export edge traces and metrics."),
        ("checkout-api", "telemetry-gateway", DependencyKind.TELEMETRY, Criticality.MEDIUM, "Export checkout traces and metrics."),
        ("payment-orchestrator", "telemetry-gateway", DependencyKind.TELEMETRY, Criticality.MEDIUM, "Export payment traces and metrics."),
    ]
    dependencies = [TopologyDependency(dependency_id=_id("dependency", f"{source}->{target}:{kind.value}"), tenant_id=TENANT_ID, source_service_id=service_ids[source], target_service_id=service_ids[target], kind=kind, criticality=criticality, description=description) for source, target, kind, criticality, description in dep_specs]

    slos: list[TopologySLO] = []
    for service in services:
        availability = 99.99 if service.tier is ServiceTier.TIER_0 else 99.9 if service.tier is ServiceTier.TIER_1 else 99.5
        latency = 350 if service.tier is ServiceTier.TIER_0 else 600 if service.tier is ServiceTier.TIER_1 else 1200
        for metric, target in [(SLOMetric.AVAILABILITY, availability), (SLOMetric.LATENCY_P95_MS, latency)]:
            slos.append(TopologySLO(slo_id=_id("slo", f"{service.slug}:production:{metric.value}"), tenant_id=TENANT_ID, service_id=service.service_id, environment_id=env_ids["production"], metric=metric, target=target, window_days=30))

    deployments: list[TopologyDeployment] = []
    base_times = {"development": datetime(2026, 8, 15, 9, 0, tzinfo=timezone.utc), "staging": datetime(2026, 8, 16, 12, 0, tzinfo=timezone.utc), "production": datetime(2026, 8, 17, 6, 0, tzinfo=timezone.utc)}
    for index, service in enumerate(services, start=1):
        for env in environments:
            version = f"2026.08.{index:02d}-{env.name[:4]}"
            deployments.append(TopologyDeployment(
                deployment_id=_id("deployment", f"{service.slug}:{env.name}:{version}"), tenant_id=TENANT_ID,
                service_id=service.service_id, environment_id=env.environment_id, version=version,
                commit_sha=_commit(service.slug, env.name), deployed_at=base_times[env.name],
                cluster=f"nexuspay-{env.name}-eu1", namespace=service.slug,
                replicas=6 if env.name == "production" and service.tier is ServiceTier.TIER_0 else 3 if env.name == "production" else 1,
            ))

    provisional = TopologySnapshot(
        seed_version=SEED_VERSION, generated_at=GENERATED_AT, seed_sha256="0" * 64,
        company=company, teams=teams, owners=owners, environments=environments, services=services,
        dependencies=dependencies, slos=slos, deployments=deployments,
    )
    payload = provisional.model_dump(mode="json")
    digest = hashlib.sha256(_payload_without_digest(payload).encode()).hexdigest()
    return provisional.model_copy(update={"seed_sha256": digest})
