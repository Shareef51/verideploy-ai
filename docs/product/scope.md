# Product Scope

## Mission
VeriDeploy AI helps engineers assess release risk, investigate incidents, analyze multimodal engineering evidence, and produce reviewed postmortems with traceable evidence.

## Personas
- Software/Platform Engineer: starts investigations and reviews technical evidence.
- Incident Commander: coordinates incident decisions and high-risk review.
- Release Engineer/SRE: evaluates release safety and runtime impact.
- Engineering Manager: reviews risk posture and postmortem outcomes.
- Platform Administrator: manages tenancy, identity, integrations and policy.

## In scope
Evidence-backed engineering investigation using authorized code/release metadata, metrics, logs, traces, documents, images, audio/video, runbooks, and synthetic demo datasets.

## Out of scope
Autonomous production rollback, autonomous deployment/configuration changes, unrestricted web access, diagnosis unrelated to engineering operations, and use of unapproved sensitive production data.

## Non-functional requirements
Tenant isolation, auditable actions, deterministic tests, typed contracts, graceful failure, idempotent async processing, observability, secure defaults, explicit approval for consequential actions, reproducible local development, and production deployability.
