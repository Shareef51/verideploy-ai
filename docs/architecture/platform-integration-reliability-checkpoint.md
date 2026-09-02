# Platform Integration and Reliability Checkpoint

Platform Integration Reliability Checkpoint verifies the foundational runtime as one system: browser, NestJS gateway, private Python AI service, workers, PostgreSQL/pgvector, Redis, Kafka, S3-compatible object storage, OIDC identity, and the OpenTelemetry/Prometheus/Grafana/Loki/Tempo observability path.

## Readiness policy

PostgreSQL, Redis, Kafka, object storage, and identity are **critical**. Loss of any critical dependency moves the platform to `not_ready`; restarting an application process must not hide that dependency failure. Once the dependency returns, readiness converges without manual database edits.

OpenTelemetry Collector, Prometheus, Grafana, Loki, and Tempo are operationally important but are **optional to request correctness**. Their loss produces `degraded` status rather than claiming the transactional platform is unavailable.

Liveness answers only whether the process is alive. Readiness is the deployment/load-balancer signal and is therefore used by Docker and Kubernetes health checks.

## Local production parity

`docker-compose.yml` intentionally mirrors the production dependency categories with local implementations:

- PostgreSQL + pgvector → managed PostgreSQL/pgvector
- Redis → managed Redis
- Kafka/KRaft → managed Kafka
- MinIO → S3-compatible object storage
- Keycloak dev realm → external OIDC provider
- OTel Collector + Prometheus/Grafana/Loki/Tempo → production observability pipeline

Compose is a local parity environment, not a production security boundary. Production Security Architecture and Kubernetes Scalability and Resilience production controls remain authoritative.

## Failure drills

`python scripts/validate_platform.py` performs deterministic smoke, restart, critical-dependency failure, optional-observability degradation, and recovery checks. These tests do not require a privileged Docker daemon and therefore run safely in CI. A real deployment can additionally exercise the existing Kubernetes pod-failure drill from Kubernetes Scalability Resilience.
