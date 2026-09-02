# Final Production Technology Architecture

Release: **0.82.0**

This document is generated from `config/architecture/production-topology.json`. It describes the deployed production boundary; it is not a conceptual alternate architecture.

## Production topology

```mermaid
flowchart LR
 U[Operator Browser] -->|OIDC PKCE| IDP[OIDC Identity]
 U -->|HTTPS| WEB[Next.js]
 WEB -->|HTTPS| GW[NestJS Gateway]
 GW -->|Private HTTPS + service identity| AI[Python AI Service]
 GW -->|Commands| K[Kafka]
 K --> W[Python Workers]
 W -->|Events| K
 AI --> LG[LangGraph]
 LG --> OAI[OpenAI]
 LG --> MCP[MCP Gateway]
 AI --> PG[(PostgreSQL + pgvector)]
 W --> PG
 AI --> R[(Redis)]
 K --> R
 R --> GW
 W --> OBJ[(Object Storage)]
 GW --> OT[OpenTelemetry]
 AI --> OT
 W --> OT
 OT --> OBS[Prometheus / Grafana / Tempo / Loki]
 K8S[Kubernetes + Helm] -. deploys .-> WEB
 K8S -. deploys .-> GW
 K8S -. deploys .-> AI
 K8S -. deploys .-> W
```

## End-to-end data flow

```mermaid
sequenceDiagram
 participant B as Browser/Next.js
 participant G as NestJS Gateway
 participant K as Kafka
 participant W as Python Worker
 participant L as LangGraph
 participant O as OpenAI/MCP/RAG
 participant P as PostgreSQL/Redis/Object Storage
 B->>G: Authenticated release-risk / RCA request
 G->>K: Durable command with tenant/correlation IDs
 K->>W: Consume ordered command
 W->>L: Start/resume durable workflow
 L->>O: Retrieval, model inference, governed tools
 O-->>L: Evidence + citations + tool results
 L->>P: Persist state/checkpoints/evidence/audit
 W->>K: Ordered progress/final events
 K-->>G: Event consumer / Redis fan-out
 G-->>B: WebSocket/SSE updates
 B->>G: Reconcile authoritative state after reconnect
```

## Boundary rules

- Next.js is the browser/operator experience; it calls NestJS only.
- NestJS is the sole public application API and realtime boundary.
- Kafka carries durable commands/events to Python workers.
- Python AI services and workers own RAG, LangGraph, OpenAI and MCP execution.
- PostgreSQL/pgvector is authoritative durable state/vector storage; Redis is cache/coordination/fan-out; object storage holds multimodal evidence.
- OIDC/PKCE and service identity protect user and service boundaries.
- Kubernetes/Helm defines production workloads; Compose provides local parity.
- OpenTelemetry feeds Prometheus/Grafana/Tempo/Loki for operations.

## Validation

`scripts/validate_production_topology.py` compares this topology model with release metadata, Helm chart/workload/image versions, Compose services, required runtime paths, and security boundary invariants.
