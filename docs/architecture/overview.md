# Architecture Overview

## Product boundary
VeriDeploy AI is an evidence-driven engineering investigation platform. The browser never calls Python directly. Next.js owns the user experience, NestJS owns the public API/security/realtime contract, and Python owns AI/RAG/workflow execution. Kafka is the durable command/event boundary.

## Initial Setup components
- **Next.js web**: authenticated-app foundation and system entry UI; no future workflow is simulated.
- **NestJS gateway**: versioned public boundary with health and correlation semantics.
- **FastAPI AI service**: private control-plane service, not browser-facing.
- **Worker runtime**: signal-safe base process for later Kafka consumers.
- **PostgreSQL/pgvector**: future system of record and vector storage.
- **Redis**: future cache, rate-limit and ephemeral coordination layer.
- **Kafka**: future durable command/domain/progress event bus.
- **MinIO**: local S3-compatible evidence object store.
- **OTel stack**: telemetry collection and local operational visibility.

## Trust boundaries
Internet/client -> Web -> public gateway -> trusted service network -> AI/workers/data stores. Future external integrations terminate behind typed adapters and MCP policy enforcement rather than LLM-direct network access.
