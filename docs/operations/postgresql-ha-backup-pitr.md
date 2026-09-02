# PostgreSQL HA, Backup, and PITR Runbook

## HA baseline
- One writable primary endpoint; one or more platform-managed standbys are recommended for production.
- Streaming replication/log shipping and failover are infrastructure responsibilities.
- Monitor replication lag, WAL retention, disk utilization, connection saturation, checkpoint pressure, and failover health.
- Keep application connection strings behind a stable database endpoint/proxy where the platform supports it.

## Backup policy
1. Take scheduled base backups suitable for PITR (for self-managed PostgreSQL, `pg_basebackup` is one supported mechanism).
2. Archive a continuous WAL sequence to storage independent of the primary.
3. Encrypt backups and archive objects; restrict restore credentials.
4. Retention must cover the declared RPO/RTO window.
5. A successful backup command is not a successful recovery program: perform recurring restore drills.

## PITR drill
1. Provision an isolated PostgreSQL target matching the supported major version.
2. Restore the selected base backup.
3. Configure WAL restore and recovery target time/LSN.
4. Start recovery and verify the target reaches the expected transaction boundary.
5. Run VeriDeploy schema/version, tenant-RLS, evidence immutability, outbox/inbox, and row-count checks.
6. Record achieved RPO/RTO and any missing WAL/base backup failures.

## Failure conditions
Do not declare backup readiness when WAL archive continuity is unknown, a base backup cannot be restored, encryption keys are unavailable, schema migration history is missing, or the restore drill has not been exercised.
