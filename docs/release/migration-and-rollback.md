# Migration and Rollback Procedure

## Forward migration
The Helm chart runs `alembic upgrade head` as a pre-install/pre-upgrade hook. Before promotion:
1. capture the current Alembic revision;
2. confirm the migration is backward compatible with the previous application version where required;
3. take/verify a recoverable database backup or PITR point;
4. deploy canary or staging first;
5. promote only after readiness, contract, RAG/agent, security, and operational gates pass.

## Application rollback
```bash
kubectl -n verideploy get deploy
helm -n verideploy history verideploy
VERIDEPLOY_ROLLBACK_APPROVED=yes scripts/release/rollback.sh <REVISION>
```
The rollback script refuses to act without explicit approval and runs post-rollback readiness checks.

## Schema rollback
Do not couple Helm rollback to an automatic destructive database downgrade. If the incident is schema-related, use an approved migration-specific procedure:
```bash
PYTHONPATH=src:. uv run alembic current
PYTHONPATH=src:. uv run alembic downgrade <reviewed_revision>
```
Only execute after impact review and backup/PITR verification. Prefer forward-fix migrations when data loss could occur.
