# Verification and Recovery Runbook

## Detect stale work
Use the trusted private stale-work endpoint or `LongRunningWorkflowCoordinator.detect_stuck()`. Only expired leases whose graph run is RUNNING, FAILED or TIMED_OUT are recoverable. Approval waits are deliberately excluded.

## Recover
A replacement worker claims the expired lease and resumes the original `run_id` and `thread_id`. Do not create a new investigation run for crash recovery. The official LangGraph checkpointer supplies the execution checkpoint.

## Side effects
All non-read-only external actions must use stable idempotency keys. A recovered workflow must query durable step state before making the external call. `completed` means return stored output; do not execute again.

## Cancellation
Cancellation writes a durable Long Running Workflow Durability cancellation event and moves the graph run to CANCELLED through the operations service. Recovery scanners must not resurrect it.

## Replay
Replay is observational. It reconstructs the ordered Long Running Workflow Durability-event stream and returns a canonical hash. It never reissues tool calls or external writes.

## Live PostgreSQL verification
`TEST_POSTGRES_URL` enables the provisioned integration test. It verifies lease CAS/takeover, RLS, terminal idempotent steps and append-only event enforcement. Without it, that test is reported as skipped and is not counted as a pass.
