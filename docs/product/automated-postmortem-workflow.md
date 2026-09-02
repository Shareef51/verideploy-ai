# Automated Postmortem Workflow

Postmortem Sequence establishes the production contract for postmortem generation without inventing evidence or prematurely implementing the later RCA and Critic agents.

## Eligibility invariant
A postmortem can be generated only when:
1. the tenant-scoped source investigation exists;
2. its authoritative status is `COMPLETED`;
3. a human-reviewed evidence bundle is supplied with reviewer identity and review timestamp;
4. every timeline and citation reference points to an ID inside that reviewed evidence set.

The worker persists the source investigation version so the report records the exact investigation state it was built from.

## Approval lifecycle
`PENDING_APPROVAL -> APPROVED | CHANGES_REQUESTED | REJECTED`

Only `APPROVED` postmortems may be exported as final Markdown or JSON. Approved reports are immutable through the Postmortem Sequence review API. Later human-review infrastructure will strengthen this boundary without changing this contract.

## Scope boundary
Postmortem Sequence assembles and validates reviewed postmortem facts. It does not fabricate RCA, citations, multimodal findings, or LLM output. Those producers are implemented in later milestones and will submit data through this contract.
