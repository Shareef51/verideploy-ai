# Final Technical Handoff

## System purpose
VeriDeploy AI is an evidence-driven release-risk and incident-intelligence platform. Browser requests enter through Next.js/NestJS, durable work is coordinated over Kafka, Python/LangGraph agents retrieve and fuse repository/runtime/multimodal evidence, consequential actions remain human-approved, and final conclusions carry stable evidence/citation IDs.

## Production boundaries
- Public: Next.js web and NestJS gateway.
- Private: Python AI service, workers, PostgreSQL/pgvector, Redis, Kafka, object storage, MCP tools, observability backends.
- External trust: OIDC identity, OpenAI, external secret store.
- Deployment: Kubernetes + Helm; Terraform installs the chart into an explicitly selected cluster context.

## Operate
Use Production Operations Checkpoint operations runbooks for alerts, Kafka replay/DLQ, backup/restore, scaling, incident response, and rollback. Use Evaluation Release Candidate Checkpoint for release-candidate evaluation evidence and Final Production Technology Architecture for the canonical topology/data-flow model.

## Explain to recruiters / senior engineers
Start with `README.md`, then `docs/recruiter/`, Final Production Technology Architecture diagrams, AI Engineering Job Description Mapping skill mapping, Resume Impact Interview Evidence interview evidence, and Recruiter Grade Readme Explanation Package demo script. Measured metrics remain linked to their historical reports; do not upgrade historical numbers without rerunning the relevant benchmark.

## Known environment-dependent validations
The source archive does not assert that a registry push, keyless signature, Terraform apply, Kubernetes rollout, external-service load test, or live restore drill occurred in this container. Those steps are automated/documented for a trusted deployment environment.
