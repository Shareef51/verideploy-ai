# Complete Testing Strategy

VeriDeploy uses an explicit eleven-suite test taxonomy: unit, integration, contract, component, graph, agent, RAG, security, chaos, Playwright, and load. `config/testing/strategy.json` is the release policy.

## Coverage policy
The Python release gate requires at least **85% global statement coverage** for `src/verideploy`; Complete Testing Strategy measured 87% in the local cumulative suite. CI measures coverage with pytest-cov and fails below the threshold.

## Mutation policy
Critical invariants are mutation-probed: event gaps must block convergence, duplicate Kafka events must not reapply, exhausted retries must reach DLQ, and terminal flows must contain citations. Any surviving critical mutant blocks release.

## CI sharding
Python tests are partitioned deterministically into four hash-based shards. Dedicated contract/security/RAG/evaluation gates remain explicit so a green shard cannot conceal a broken critical subsystem. Playwright and load/chaos suites are independently addressable.

External PostgreSQL/pgvector tests remain conditional on `TEST_POSTGRES_URL`; they are required in the integration environment rather than silently replaced by mocks.
