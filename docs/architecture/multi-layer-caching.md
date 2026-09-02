# Multi-Layer Caching

## Goal

Provide one production cache contract for integration responses, retrieval results, model-safe outputs, authorization decisions, and sessions. Redis is mandatory in production; the in-memory backend exists only for deterministic tests/local execution.

## Cache layers

| Layer | Fresh TTL | Stale window | Encryption | Special rule |
|---|---:|---:|---|---|
| integration | 60s | 120s | no | bounded stale fallback during upstream failure |
| retrieval | 120s | 180s | no | authorization scope fingerprint is part of the key |
| model_output | 300s | 60s | AES-256-GCM | output must be explicitly marked model-safe |
| permission | 30s | none | AES-256-GCM | no stale authorization decisions |
| session | 900s | none | AES-256-GCM | no stale sessions |

The values are policy-driven in `config/cache/policy.json` and can be changed without modifying cache code.

## Key isolation

Keys are deterministic hashes of:

`key version + environment + layer + tenant + namespace + authorization/scope fingerprint + logical key`

Tenant IDs and logical inputs are hashed before entering Redis keys. A cache entry created for one tenant or authorization scope cannot be found using another tenant/scope key.

## Stampede control

`get_or_load()` uses an atomic Redis `SET NX EX` lock. The lock owner rechecks cache state before calling the origin. Concurrent callers either:

1. observe the freshly populated value,
2. coalesce while waiting for the lock owner, or
3. use a bounded stale value if policy permits it.

If the origin fails while an allowed stale value exists, the stale value is returned as `stale_fallback`. Permission and session layers have no stale window.

## Invalidation

Entries can carry tenant-scoped tags. Tag invalidation removes all matching keys only within the same tenant/layer/environment partition. Integration webhooks, document re-indexing, permission changes, model/prompt promotion, and session revocation should invalidate their corresponding tags.

## Encryption policy

Sensitive layers are encrypted before Redis persistence with AES-256-GCM. The encryption key is deterministically derived per tenant from `CACHE_ENCRYPTION_SECRET`; tenant/layer/environment/scope data is bound as authenticated associated data. Production startup fails unless Redis is selected. A dedicated `CACHE_ENCRYPTION_SECRET` may be configured; otherwise the already-required strong application secret is domain-separated by the cache cipher derivation. Any dedicated cache secret must be at least 32 bytes.

## Observability and failure policy

Cache consumers receive explicit statuses: `miss`, `fresh`, `stale`, `loaded`, `coalesced`, `stale_fallback`, or `expired`. Callers can map these to OpenTelemetry metrics without logging cache values. Sensitive contents must never be span attributes or logs.

## Milestone gate

The CI benchmark proves:

- 40 concurrent misses trigger one origin load,
- tenant isolation prevents cross-tenant hits,
- tag invalidation is scoped,
- sensitive session bytes do not contain plaintext,
- all five cache layers are registered.
