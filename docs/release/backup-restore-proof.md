# Backup / Restore Proof Contract

The repository includes both the production recovery policy and an executable restored-database verifier. A successful backup alone is not considered proof of recoverability.

## Existing controls
- `docs/operations/postgresql-ha-backup-pitr.md` defines HA, WAL archive, PITR, retention, and failure conditions.
- `docs/operations/database-backup-restore.md` defines logical backup and isolated restore steps.
- `scripts/verify_database_restore.py` verifies Alembic revision, pgvector, HNSW index, RLS, and forced RLS on a restored target.

## Required production evidence
For each release or scheduled recovery drill, retain: release version, source commit, DB engine/pgvector versions, backup object/version, backup SHA-256, recovery target, restore start/end timestamps, achieved RPO/RTO, verifier output, and operator/approver identity.

## Truthfulness status for this handoff
The source package validates that the restore verifier and procedures are present and consistent. This execution environment did not provide a live production PostgreSQL backup/PITR target, so Backup Restore Proof does **not** claim a live restore drill was performed here. The final deployment gate requires that live evidence before production promotion.
