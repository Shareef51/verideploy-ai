from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict

from verideploy.incidents.generator import _incident_digest
from verideploy.incidents.schemas import FailureMode, IncidentDataset, IncidentDatasetValidationReport


def _dataset_digest(dataset: IncidentDataset) -> str:
    payload = dataset.model_dump(mode="json")
    payload["dataset_sha256"] = ""
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def validate_incident_dataset(dataset: IncidentDataset) -> IncidentDatasetValidationReport:
    errors: list[str] = []
    incidents = list(dataset.incidents)
    if len(incidents) < 200:
        errors.append("dataset must contain at least 200 incidents")
    if _dataset_digest(dataset) != dataset.dataset_sha256:
        errors.append("dataset SHA-256 mismatch")

    label_counts = Counter(i.failure_mode.value for i in incidents)
    split_counts = Counter(i.split.value for i in incidents)
    required = {m.value for m in FailureMode}
    if set(label_counts) != required:
        errors.append("failure-mode coverage is incomplete")
    if label_counts and max(label_counts.values()) - min(label_counts.values()) > 1:
        errors.append("failure-mode labels are imbalanced")

    ids = [i.incident_id for i in incidents]
    if len(ids) != len(set(ids)):
        errors.append("duplicate incident IDs")
    family_splits: dict[object, set[str]] = defaultdict(set)
    for incident in incidents:
        family_splits[incident.family_id].add(incident.split.value)
        if _incident_digest(incident.model_copy(update={"incident_sha256":"0"*64})) != incident.incident_sha256:
            errors.append(f"incident hash mismatch: {incident.incident_id}")
        times = [e.timestamp for e in incident.timeline]
        if times != sorted(times):
            errors.append(f"timeline is not ordered: {incident.incident_id}")
        if not any(m.causal for m in incident.metrics) or not any(l.causal for l in incident.logs) or not any(t.causal for t in incident.traces):
            errors.append(f"causal modality coverage missing: {incident.incident_id}")
        if not any(not m.causal for m in incident.metrics) or not any(not l.causal for l in incident.logs) or not any(not t.causal for t in incident.traces):
            errors.append(f"non-causal noise coverage missing: {incident.incident_id}")
        observable = " ".join([
            *(m.metric for m in incident.metrics), *(l.message for l in incident.logs), *(t.operation for t in incident.traces),
            *(e.summary for e in incident.timeline), incident.trigger_summary,
        ]).lower()
        if incident.failure_mode.value.lower() in observable:
            errors.append(f"label leakage detected: {incident.incident_id}")
        if incident.resolution.resolved_at != incident.resolved_at:
            errors.append(f"resolution time mismatch: {incident.incident_id}")
    if any(len(splits) > 1 for splits in family_splits.values()):
        errors.append("incident family appears in multiple dataset splits")
    if not {"train", "validation", "test"}.issubset(split_counts):
        errors.append("train/validation/test split coverage is incomplete")

    return IncidentDatasetValidationReport(valid=not errors, dataset_sha256=dataset.dataset_sha256, incident_count=len(incidents), label_counts=dict(sorted(label_counts.items())), split_counts=dict(sorted(split_counts.items())), errors=tuple(errors))
