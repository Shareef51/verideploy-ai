# Agentic Orchestration Checkpoint

Agentic Orchestration Checkpoint hardens the existing VeriDeploy supervisor/planner/specialist-agent architecture rather than introducing a second graph runtime.

## Protected orchestration paths

The checkpoint covers deterministic release-risk fan-out/fan-in, incident RCA with a bounded transient retry and durable restart recovery, and a critic correction loop that performs bounded read-only follow-up retrieval before stopping at the human approval boundary.

## Invariants

- supervisor routing is deterministic for protected scenarios;
- planner order and tool selection match policy;
- fan-out branches must converge through deterministic fan-in before synthesis;
- retries may not exceed the configured budget;
- durable completed steps remain idempotently completed after worker restart;
- critic correction must either resolve unsupported material claims or escalate;
- consequential paths stop at human approval;
- every modeled failure carries trace and span linkage;
- protected path metrics must meet the configured thresholds.

The CI checkpoint is dependency-free by design and complements, rather than replaces, the real LangGraph/PostgreSQL integration tests.
