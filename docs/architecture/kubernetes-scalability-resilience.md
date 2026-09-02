# Kubernetes Scalability and Resilience

Kubernetes Scalability Resilience turns the existing containerized VeriDeploy services into a production Kubernetes deployment contract. The Helm chart is deliberately conservative: stable workloads use native Deployments with zero-unavailable rolling updates, a canary is opt-in, schema migration runs as a pre-install/pre-upgrade hook, and rollback remains an explicit operator action.

## Production workload contract

The chart deploys `web`, `gateway`, `ai-service`, and `worker`. Each stable workload has three replicas by default, CPU/memory requests and limits, a PodDisruptionBudget with `minAvailable: 2`, HPA v2, topology spreading across both zone and hostname, and pod anti-affinity. HTTP workloads have startup/readiness/liveness probes; the worker uses process-level exec probes. Containers run non-root with RuntimeDefault seccomp, read-only root filesystems, no privilege escalation, and all Linux capabilities dropped.

## Dependencies and networking

PostgreSQL, Redis, Kafka, and the object store remain externally configurable dependencies. Runtime credentials/endpoints enter through the existing Kubernetes Secret rather than chart literals. NetworkPolicy starts from default deny and opens only workload-local traffic, DNS, configured dependency ports, and HTTPS egress required for authorized external integrations. Production Security Architecture security assumptions remain authoritative.

## Migration safety

The Alembic migration Job runs before install/upgrade and has bounded retry plus an active deadline. A failed migration prevents the Helm rollout from becoming healthy; it is never hidden behind application readiness.

## Canary and rollback

`canary.enabled` is false by default. Enabling it creates a separately selected gateway canary Deployment and Service, with a declared maximum traffic percentage annotation. The chart does not silently reroute stable traffic. `scripts/deploy/canary.sh` provides deploy, promote, rollback, and status operations and uses Helm `--atomic --wait` for deploy/promotion. External ingress/service-mesh weighting can target the canary service without changing the stable selector.

## Multi-AZ assumptions

Production clusters are assumed to expose `topology.kubernetes.io/zone` and `kubernetes.io/hostname`. The default three replicas and `minAvailable: 2` are validated against a three-AZ placement model: one pod loss or one balanced AZ loss keeps the minimum serving capacity. This is a deployment assumption, not a claim that a local validation run exercised a real cloud control plane.

## Validation

Run:

```bash
PYTHONPATH=src python scripts/validate_kubernetes.py
PYTHONPATH=src pytest -q tests/platform/test_kubernetes_scalability_resilience.py
```

When Helm and a target cluster are available, operators should additionally run `helm lint`, `helm template`, server-side dry-run, and a real controlled pod-eviction drill before production promotion. The repository CI gate remains paid-service-free and cluster-independent.
