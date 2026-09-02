# NexusPay Service Topology Verification

Generate and validate the stable seed:

```bash
make topology-generate
make topology-validate
```

Persist it after database migrations in a provisioned PostgreSQL environment:

```bash
make migrate
make topology-seed
```

The seed command is idempotent. It does not use an in-memory repository in production. Validate the UI after starting the normal stack at `/topology`.

The local CI-safe gate verifies stable digest, reference integrity, acyclic application dependencies, team ownership, production SLO/deployment coverage, private API authorization, gateway routing, and frontend source rendering. Live PostgreSQL persistence is not claimed unless `TEST_POSTGRES_URL` or the full stack is provisioned.
