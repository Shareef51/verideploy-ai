# Synthetic Kubernetes Operations: Checkout API

checkout-api runs as a synthetic Kubernetes Deployment across multiple replicas. Readiness failure removes a pod from service before restart policy decisions are considered. Investigation evidence should distinguish pod restarts, scheduling pressure, application saturation, and downstream dependency latency.

A deployment change that increases process concurrency can raise effective downstream connection demand even when pod replica count is unchanged. Kubernetes health alone therefore cannot prove database health or rule out application-level pool exhaustion.

Operational checks are read-only by default. Scaling, rollout restart, rollback, or configuration mutation requires the appropriate later-milestone action policy and human approval boundary.
