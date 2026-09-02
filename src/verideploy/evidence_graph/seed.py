from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from verideploy.evidence_graph.schemas import GraphEdgeCreate, GraphEntityCreate, GraphEntityType, GraphRelationship
from verideploy.evidence_graph.service import EvidenceGraphService


def _dt(value: str): return datetime.fromisoformat(value.replace("Z", "+00:00"))


def seed_nexuspay_demo_graph(service: EvidenceGraphService, *, dataset_path: str | Path = "data/incidents/nexuspay-incidents.json"):
    data=json.loads(Path(dataset_path).read_text()); incident=data["incidents"][0]; tenant=UUID(incident["tenant_id"])
    service_id=incident["primary_service_id"]; commit=incident["release"]["commit_sha"]
    entities=[
      GraphEntityCreate(tenant_id=tenant,entity_type=GraphEntityType.PULL_REQUEST,natural_key=f"nexuspay/pr/{commit[:8]}",label=f"PR for {incident['release']['version']}",reference_uri=f"github://nexuspay/checkout/pulls/{int(commit[:4],16)%900+100}",attributes={"commit_sha":commit,"synthetic":True},observed_at=_dt(incident["release"]["deployed_at"])),
      GraphEntityCreate(tenant_id=tenant,entity_type=GraphEntityType.SERVICE,natural_key=f"service/{service_id}",label="Checkout API",reference_uri=f"topology://service/{service_id}",attributes={"service_id":service_id,"synthetic":True},observed_at=_dt(incident["release"]["deployed_at"])),
      GraphEntityCreate(tenant_id=tenant,entity_type=GraphEntityType.INCIDENT,natural_key=f"incident/{incident['incident_id']}",label=f"Incident {incident['incident_id'][:8]}",reference_uri=f"incident://{incident['incident_id']}",attributes={"failure_mode":incident["failure_mode"],"severity":incident["severity"],"synthetic":True},observed_at=_dt(incident["started_at"])),
      GraphEntityCreate(tenant_id=tenant,entity_type=GraphEntityType.ROOT_CAUSE,natural_key=f"cause/{incident['incident_id']}",label=incident["root_cause_summary"],reference_uri=f"rca://{incident['incident_id']}/root-cause",attributes={"failure_mode":incident["failure_mode"],"synthetic":True},observed_at=_dt(incident["detected_at"])),
      GraphEntityCreate(tenant_id=tenant,entity_type=GraphEntityType.EVIDENCE,natural_key=f"log/{incident['logs'][0]['log_id']}",label="Causal log evidence",reference_uri=f"incident://{incident['incident_id']}/log/{incident['logs'][0]['log_id']}",attributes={"message":incident["logs"][0]["message"],"synthetic":True},observed_at=_dt(incident["logs"][0]["timestamp"])),
    ]
    rows=[service.put_entity(e) for e in entities]; by_type={e.entity_type:e for e in rows}
    edge_inputs=[
      (GraphEntityType.PULL_REQUEST,GraphRelationship.MODIFIES_SERVICE,GraphEntityType.SERVICE,_dt(incident["release"]["deployed_at"]),0.98),
      (GraphEntityType.SERVICE,GraphRelationship.EXPERIENCED_INCIDENT,GraphEntityType.INCIDENT,_dt(incident["started_at"]),1.0),
      (GraphEntityType.INCIDENT,GraphRelationship.CAUSED_BY,GraphEntityType.ROOT_CAUSE,_dt(incident["detected_at"]),0.96),
      (GraphEntityType.ROOT_CAUSE,GraphRelationship.SUPPORTED_BY,GraphEntityType.EVIDENCE,_dt(incident["logs"][0]["timestamp"]),0.94),
    ]
    for src,rel,tgt,when,conf in edge_inputs:
        service.put_edge(GraphEdgeCreate(tenant_id=tenant,source_entity_id=by_type[src].entity_id,target_entity_id=by_type[tgt].entity_id,relationship=rel,confidence=conf,occurred_at=when,valid_from=when,attributes={"synthetic":True}))
    return service.snapshot(tenant_id=tenant)
