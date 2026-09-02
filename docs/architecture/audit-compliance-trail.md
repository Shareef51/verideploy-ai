# Audit and Compliance Trail

Audit Compliance Trail centralizes consequential-action reconstruction around an append-only, tenant-scoped audit envelope. The production PostgreSQL table is immutable except for retention-authorized deletion after `retain_until` and only when no legal hold is active.

## Audit envelope
Every event records actor type/id/roles, resource type/id/tenant, action, result, correlation ID, optional trace/span IDs, source, reason code, redacted payload, retention class, legal hold, previous hash, event hash, and optional review signature.

## Tamper evidence
Events form a per-tenant SHA-256 hash chain. PostgreSQL enforces unique sequence and event hashes plus append-only triggers. Production deployments should periodically anchor the current chain head in an external immutable store/KMS-backed evidence record.

## Search and export
Search is tenant-scoped and role-authorized. Export is limited to `auditor` and `security_admin`, supports JSONL/CSV, and includes an export SHA-256. Secret-like keys, authorization headers, cookies, tokens, passwords, and bearer strings are redacted before persistence/hash generation.

## Retention
`standard` defaults to 365 days; `security` and `legal` default to 2555 days. Legal hold prevents purge. Retention deletion requires the database session flag `app.audit_retention_purge=on` and an expired event with no hold.

## UI/API
`/audit` uses AG Grid and reads only through Next.js → NestJS → private FastAPI. Browser code never reaches the private AI service directly.

## Gate
`PYTHONPATH=src python scripts/benchmark_audit_trail.py` must pass, and cumulative tests must prove tamper detection, signature verification, tenant isolation, export authorization, retention semantics, and viewer/API presence.
