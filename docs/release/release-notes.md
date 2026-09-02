# VeriDeploy AI 0.86.0 — Final Production Handoff

Release 0.86.0 closes the 86-milestone cumulative build. It preserves the Recruiter Grade Readme Explanation Package recruiter package and adds the production release boundary: versioned container definitions, Terraform deployment plan, Helm release integration, explicit migration/rollback, backup/restore verification contract, signed-artifact CI, deployment verification, demo seeding, and final handoff documentation.

## Release scope
- Next.js web, NestJS gateway, Python AI service, and Python worker image definitions are versioned at `0.86.0`.
- Helm chart/app version and production values are aligned to `0.86.0`.
- Terraform deploys the existing Helm chart into an explicitly selected Kubernetes context and namespace; it does not create cloud accounts, managed databases, Kafka, Redis, object storage, or identity providers implicitly.
- External Secrets remains the production secret boundary.
- Consequential actions remain dry-run / human-approval governed.

## Local verification status
Repository tests and release-contract checks can run locally. Registry push, keyless Sigstore signing, Terraform apply, Kubernetes rollout, and a live PostgreSQL restore drill require a trusted CI/cluster environment and are not represented as executed by this source archive.
