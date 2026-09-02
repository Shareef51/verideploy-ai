# Human-in-the-Loop Approval

## Purpose
Human in the Loop Approval adds a durable, concurrency-safe human approval boundary for high-risk VeriDeploy actions. A high-risk production decision cannot become executable merely because an agent proposes it. The workflow must create a durable approval request, expose it to an eligible reviewer queue, record a signed decision event, and authorize graph resume only after the approval is terminal `approved`.

## Flow
1. Review policy evaluates risk score and risk class.
2. `ApprovalRuntimeBridge.interrupt_for_review()` persists the approval request, changes the LangGraph Production Runtime graph run to `WAITING_FOR_APPROVAL`, and appends `graph.approval.interrupted`.
3. Reviewers consume the queue through Next.js → NestJS → private FastAPI.
4. Approve, reject, request-change, delegation, and expiry transitions are versioned.
5. Every transition produces an HMAC-SHA256 signed append-only audit event.
6. PostgreSQL row locking plus expected-version checks ensure concurrent terminal decisions have one winner.
7. A deferred PostgreSQL constraint requires every request version transition to have a matching signed event by commit.
8. `ApprovalRuntimeBridge.resume_approved()` refuses resume unless the approval belongs to the run and is currently approved.

## Database authority
`approval_requests` is the current approval state. `approval_events` is immutable audit history. Both are tenant-RLS protected. Approval events cannot be updated or deleted. Request lifecycle changes must increment version exactly once and follow allowed transitions.

## Signed audit model
The application signs canonical event data with HMAC-SHA256 using `APPROVAL_SIGNING_SECRET`, falling back to `APP_SECRET_KEY` when a dedicated key is not configured. Only the signature and payload digest are persisted; the signing key never enters the database.

## Concurrency invariant
For one approval version, exactly one terminal state transition may win. A stale or simultaneous decision receives `ApprovalConflictError`/HTTP 409. Direct SQL cannot create a valid terminal state without a matching signed event because the deferred transition-event constraint validates the pair at transaction commit.

## Reviewer queue
The queue sorts active requests by descending risk score, then expiry. Reviewer role eligibility and delegation are checked server-side. Browser clients do not supply the trusted internal service identity or authoritative reviewer role grants.
