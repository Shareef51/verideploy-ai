# Synthetic Service Profile: checkout-api

checkout-api owns the synchronous checkout request path for the synthetic VeriDeploy portfolio environment. The service depends on postgres-primary for transactional state, redis-cache for short-lived caching, and kafka-orders for downstream order events.

Primary indicators include request success rate, p50/p95/p99 latency, database connection wait time, active connection count, trace error rate, and queue depth. The production environment target is 99.95 percent monthly availability. The service owner is the synthetic Commerce Platform team.

Known investigation context includes sensitivity to database pool sizing when worker concurrency changes. This is synthetic seed knowledge and must not be presented as evidence about any real company or production service.
