# Configuration and secret rotation runbook

1. Create a new version in the approved external secret provider.
2. Keep the previous version valid during the configured grace period.
3. Allow External Secrets / deployment integration to refresh the Kubernetes Secret.
4. Roll workloads so startup validation re-evaluates configuration.
5. Verify health/readiness, audit entries, and zero client-bundle secret references.
6. Revoke the previous secret after the grace period.
7. Record owner, ticket, provider version, timestamps, and rollback decision in the audit trail.

Never print secret values in logs, CI annotations, test snapshots, or browser configuration.
