# Supply-chain release runbook
1. Generate `pnpm-lock.yaml` and `uv.lock` in a trusted networked builder; commit/review changes.
2. Resolve Docker base tags to immutable OCI digests and update `config/supply-chain/base-images.json` plus Dockerfiles.
3. Generate CycloneDX and SPDX SBOMs with an approved scanner.
4. Scan dependencies/images; HIGH/CRITICAL findings block unless a non-expired documented exception exists.
5. Build artifacts; record SHA-256, commit SHA, repository, workflow and CI run ID.
6. Sign images and provenance using keyless Sigstore/cosign in CI; verify before promotion.
7. Run `python scripts/validate_supply_chain.py --release` before publishing.
