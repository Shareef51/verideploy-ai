from __future__ import annotations

import hashlib
import json
import random
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid5

from verideploy.incidents.schemas import (
    FailureMode, IncidentDataset, IncidentResolution, IncidentSeverity, IncidentSplit,
    LogRecord, MetricPoint, ReleaseEvidence, SyntheticIncident, TimelineEvent, TraceSpan,
)
from verideploy.topology.seed import NAMESPACE, build_nexuspay_topology

DATASET_NAMESPACE = UUID("d7bddf15-a7fd-5e74-9caa-ffec9985a929")
SEED_VERSION = "nexuspay-v1"
SEED = 29029
GENERATED_AT = datetime(2026, 8, 17, 18, 30, tzinfo=timezone.utc)

MODE_SPECS = {
    FailureMode.DB_POOL_EXHAUSTION: ("checkout-api", "Database connections reached the configured ceiling and requests queued.", "Increase pool capacity after verifying database connection budget and remove leaked sessions.", "db.active_connections", 98.0),
    FailureMode.INCOMPATIBLE_SCHEMA_MIGRATION: ("ledger-service", "Application reads encountered a schema shape incompatible with the deployed binary.", "Roll back the release and restore the compatible schema contract before redeploying.", "db.query_errors", 42.0),
    FailureMode.TLS_CERTIFICATE_EXPIRY: ("api-gateway", "TLS handshakes began failing after the serving certificate became invalid.", "Rotate the certificate, validate the chain, and reload the edge listener.", "tls.handshake_errors", 75.0),
    FailureMode.CACHE_MEMORY_PRESSURE: ("pricing-service", "Cache memory approached its eviction threshold and hit rate collapsed.", "Reduce cache pressure, restore memory headroom, and verify hit-rate recovery.", "cache.evictions", 420.0),
    FailureMode.CONSUMER_LAG: ("ledger-service", "Event consumption fell behind producers and settlement processing accumulated backlog.", "Scale consumers and remove the slow processing path before draining backlog.", "messaging.backlog_records", 18000.0),
    FailureMode.DOWNSTREAM_TIMEOUT: ("payment-orchestrator", "Calls to a required downstream dependency exceeded the client timeout budget.", "Restore downstream latency and keep retries within the payment idempotency policy.", "http.client_deadline_exceeded_rate", 0.38),
    FailureMode.CPU_SATURATION: ("fraud-engine", "Compute utilization remained saturated and request latency rose with queue depth.", "Reduce hot-path compute cost and add capacity until utilization and latency recover.", "process.cpu.utilization", 0.97),
    FailureMode.BAD_CONFIGURATION: ("identity-service", "A newly applied runtime setting referenced an invalid issuer endpoint and authentication checks failed.", "Restore the last known-good configuration and validate settings before rollout.", "auth.validation_failures", 315.0),
}


def _id(kind: str, value: str) -> UUID:
    return uuid5(DATASET_NAMESPACE, f"{kind}:{value}")


def _hex(kind: str, value: str, length: int) -> str:
    return hashlib.sha256(f"{kind}:{value}".encode()).hexdigest()[:length]


def _canonical_without_digest(payload: dict, field: str) -> str:
    clone = dict(payload)
    clone[field] = ""
    return json.dumps(clone, sort_keys=True, separators=(",", ":"), default=str)


def _split(index: int) -> IncidentSplit:
    pos = index % 10
    if pos < 7:
        return IncidentSplit.TRAIN
    if pos < 9:
        return IncidentSplit.VALIDATION
    return IncidentSplit.TEST


def _incident_digest(incident: SyntheticIncident) -> str:
    payload = incident.model_dump(mode="json")
    return hashlib.sha256(_canonical_without_digest(payload, "incident_sha256").encode()).hexdigest()


def build_incident_dataset(count_per_label: int = 30) -> IncidentDataset:
    if count_per_label < 25:
        raise ValueError("dataset requires at least 200 incidents; use >=25 per eight labels")
    rng = random.Random(SEED)
    topology = build_nexuspay_topology()
    services = {s.slug: s for s in topology.services}
    prod = next(e for e in topology.environments if e.name == "production")
    prod_deployments = {d.service_id: d for d in topology.deployments if d.environment_id == prod.environment_id}
    incidents: list[SyntheticIncident] = []

    for mode_index, mode in enumerate(FailureMode):
        service_slug, causal_text, resolution_action, metric_name, metric_peak = MODE_SPECS[mode]
        service = services[service_slug]
        deployment = prod_deployments[service.service_id]
        for index in range(count_per_label):
            key = f"{mode.value}:{index:03d}"
            family_id = _id("family", key)
            incident_id = _id("incident", key)
            started = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(days=mode_index * 35 + index, hours=(index * 3) % 24)
            detected = started + timedelta(minutes=3 + (index % 5))
            resolved = started + timedelta(minutes=35 + (index % 31))
            release_time = started - timedelta(minutes=20 + index % 90)
            release_related = mode in {FailureMode.INCOMPATIBLE_SCHEMA_MIGRATION, FailureMode.BAD_CONFIGURATION}
            release = ReleaseEvidence(
                deployment_id=deployment.deployment_id,
                version=f"incident-{2026}{mode_index+1:02d}.{index:03d}",
                commit_sha=_hex("commit", key, 40),
                deployed_at=release_time,
                causally_related=release_related,
            )
            baseline = metric_peak * (0.10 + 0.03 * rng.random())
            metrics = (
                MetricPoint(metric=metric_name, timestamp=started - timedelta(minutes=10), value=round(baseline, 5), unit="ratio" if metric_peak < 1 else "count", causal=True),
                MetricPoint(metric=metric_name, timestamp=detected, value=round(metric_peak * (0.92 + 0.08 * rng.random()), 5), unit="ratio" if metric_peak < 1 else "count", causal=True),
                MetricPoint(metric="http.request_rate", timestamp=detected, value=round(120 + rng.random() * 50, 3), unit="rps", causal=False),
            )
            logs = (
                LogRecord(log_id=_id("log", key+":1"), timestamp=started + timedelta(minutes=1), level="ERROR", service_id=service.service_id, message=causal_text, causal=True),
                LogRecord(log_id=_id("log", key+":2"), timestamp=started + timedelta(minutes=2), level="INFO", service_id=service.service_id, message="Periodic health probe completed while incident investigation was active.", causal=False),
            )
            traces = (
                TraceSpan(trace_id=_hex("trace", key, 32), span_id=_hex("span", key+":1", 16), timestamp=started + timedelta(minutes=2), service_id=service.service_id, operation=f"{service.slug}.request", duration_ms=round(900 + rng.random()*1800, 2), status="ERROR", causal=True),
                TraceSpan(trace_id=_hex("trace", key+":noise", 32), span_id=_hex("span", key+":2", 16), timestamp=started + timedelta(minutes=2, seconds=30), service_id=service.service_id, operation=f"{service.slug}.health", duration_ms=round(8+rng.random()*10, 2), status="OK", causal=False),
            )
            trigger = "A production release preceded the first failing signal." if release_related else "Normal production load exposed the latent failure condition."
            timeline = (
                TimelineEvent(event_id=_id("event", key+":release"), timestamp=release_time, kind="release", summary="Production deployment completed.", causal=release_related),
                TimelineEvent(event_id=_id("event", key+":signal"), timestamp=started + timedelta(minutes=1), kind="signal", summary="First causal telemetry signal crossed the incident threshold.", causal=True),
                TimelineEvent(event_id=_id("event", key+":impact"), timestamp=detected, kind="impact", summary="Customer-facing reliability impact confirmed by on-call.", causal=True),
                TimelineEvent(event_id=_id("event", key+":mitigation"), timestamp=resolved - timedelta(minutes=8), kind="mitigation", summary="On-call applied the scenario-specific safe mitigation.", causal=True),
                TimelineEvent(event_id=_id("event", key+":resolution"), timestamp=resolved, kind="resolution", summary="Signals returned to the expected operating range.", causal=True),
            )
            resolution = IncidentResolution(resolved_at=resolved, action=resolution_action, verification="Causal metric and failing request path returned to the pre-incident baseline for fifteen minutes.")
            provisional = SyntheticIncident(
                incident_id=incident_id, family_id=family_id, tenant_id=topology.company.tenant_id, split=_split(index),
                failure_mode=mode, severity=IncidentSeverity.SEV1 if mode_index % 4 == 0 else IncidentSeverity.SEV2 if mode_index % 3 else IncidentSeverity.SEV3,
                primary_service_id=service.service_id, environment_id=prod.environment_id,
                started_at=started, detected_at=detected, resolved_at=resolved, release=release,
                metrics=metrics, logs=logs, traces=traces, timeline=timeline, resolution=resolution,
                root_cause_summary=causal_text, trigger_summary=trigger, incident_sha256="0"*64,
            )
            incidents.append(provisional.model_copy(update={"incident_sha256": _incident_digest(provisional)}))

    provisional_dataset = IncidentDataset(seed_version=SEED_VERSION, seed=SEED, generated_at=GENERATED_AT, topology_sha256=topology.seed_sha256, dataset_sha256="0"*64, incidents=tuple(incidents))
    payload = provisional_dataset.model_dump(mode="json")
    digest = hashlib.sha256(_canonical_without_digest(payload, "dataset_sha256").encode()).hexdigest()
    return provisional_dataset.model_copy(update={"dataset_sha256": digest})
