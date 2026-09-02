# Multimodal Evidence Workflow Verification

Verified on 2026-08-16 in the artifact build environment.

## Passed checks

- `pytest -q`: **28 passed** cumulative tests.
- Focused Multimodal Sequence tests: **8 passed**.
- `python -m compileall -q services src workers tests`: passed.
- `python scripts/validate_contracts.py`: passed; Multimodal Sequence REST and Kafka contracts present and parseable.
- Docker Compose YAML plus package JSON parse: passed.
- TypeScript/TSX syntax transpilation with the installed TypeScript compiler: **29 source files passed** (declaration file excluded from transpilation).
- FastAPI `/health/live`: HTTP 200, `ok`.
- FastAPI `/health/ready`: HTTP 200, `ready` for dependencies implemented by the private service in the current milestone.
- Focused Multimodal Sequence placeholder scan: clean.
- Repository secret-pattern scan for common API-key/private-key signatures: clean.
- Final ZIP integrity check: recorded in `artifacts/verification-04-multimodal-sequence.txt` after archive creation.

## Multimodal Sequence behaviors covered by executable tests

- strict ingestion command schema validation;
- unsafe/path-like original filename rejection;
- SHA-256 format validation;
- durable tenant-scoped ingestion state;
- idempotent duplicate command handling;
- monotonic sequenced event journal;
- durable event replay after a cursor;
- invalid Kafka payload rejection;
- private service identity enforcement;
- cross-tenant job lookup denial.

## Environment-constrained checks

The build environment does not provide Docker Engine, pnpm, Ruff, or MyPy executables and cannot perform registry installation. Therefore these checks are **not claimed as passed** here:

- live Docker Compose startup with PostgreSQL/Kafka/MinIO;
- real S3/MinIO PutObject integration from NestJS;
- real Kafka producer/consumer integration across containers;
- dependency-aware NestJS/Next.js build, lint, typecheck, Jest/Vitest or browser tests;
- Ruff and MyPy execution.

The repository includes Compose bootstrap services for the MinIO bucket and required Kafka topics so these checks can run in a clean developer/CI environment with the documented prerequisites.
