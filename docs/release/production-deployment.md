# Production Deployment

## Prerequisites
A clean operator environment needs Git, Docker/BuildKit, Terraform >=1.8, Helm 3, kubectl, cosign, a Kubernetes context, External Secrets Operator, and reachable managed PostgreSQL/pgvector, Redis, Kafka, S3-compatible object storage, OIDC, and OpenAI endpoints. Runtime credentials must exist in the configured external secret store; never place them in tfvars, Helm values, or Git.

## 1. Verify source
```bash
sha256sum -c VeriDeploy_AI_v0.86.0.sha256
PYTHONPATH=src python scripts/validate_release.py
```

## 2. Build/sign release images
Preferred path: push tag `v0.86.0` and run `.github/workflows/release.yml`. The workflow builds and pushes web, gateway, AI, and worker images, generates provenance/SBOM metadata, signs image digests with keyless cosign, verifies signatures, packages Helm, creates a Terraform plan, and signs release blobs.

## 3. Prepare Terraform
```bash
cd infrastructure/terraform
cp terraform.tfvars.example terraform.tfvars
# Set only non-secret deployment coordinates.
terraform init
terraform validate
terraform plan -out=verideploy-0.86.0.tfplan
```

## 4. Apply only after release approval
```bash
VERIDEPLOY_RELEASE_APPROVED=yes ../../scripts/release/deploy.sh
```
The script refuses to apply without the explicit approval variable.

## 5. Verify rollout and observability
```bash
../../scripts/release/verify.sh
```
Verify deployments, services, readiness, ExternalSecret status, migration hook success, Kafka connectivity, and OTel/Prometheus visibility.

## 6. Seed and run the synthetic recruiter demo
```bash
VERIDEPLOY_TENANT_ID=synthetic-demo VERIDEPLOY_USER_ID=recruiter-demo ../../scripts/release/seed_demo.sh
```
The seed script calls the public demo API; it does not edit the production database manually.

## Rollback
Follow `migration-and-rollback.md`. Application rollback uses Helm history/rollback and never silently downgrades schema. Any schema rollback requires an explicitly reviewed Alembic step and restore contingency.
