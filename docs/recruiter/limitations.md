# Known Limitations and Production Validation Still Required

This repository is production-oriented portfolio engineering, not evidence that a specific enterprise deployment has already operated at customer scale.

1. **Managed-cloud validation:** repeat Helm/Terraform/dependency validation against the target cloud, managed Kafka/PostgreSQL/Redis/object storage, network policies, KMS, and external secret manager.
2. **Real browser execution:** the release workflow contains mandatory Playwright CI coverage; browser execution must be observed in a provisioned runner before final production sign-off.
3. **Live dependency drills:** Docker/Kubernetes restart, dependency-failure, backup/restore, Kafka replay/DLQ, and rollback drills must be executed in the target environment and retained as evidence.
4. **Provider/network benchmarks:** deterministic RAG/eval latency protects algorithmic regression; it is not a substitute for live OpenAI/network/database latency and cost measurement.
5. **Supply-chain release material:** release mode requires network-generated lockfiles, vulnerability/license scans, immutable image digests, SBOMs, provenance, and signatures. Offline builds must not fabricate these.
6. **Data/privacy review:** use synthetic/public/authorized data. A real enterprise deployment needs organization-specific privacy, retention, legal, and compliance review.
7. **Human responsibility:** AI output supports engineering decisions; it does not replace accountable release/incident owners. Consequential actions remain approval-gated.
