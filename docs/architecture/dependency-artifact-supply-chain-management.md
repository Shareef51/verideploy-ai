# Dependency, Artifact, and Supply-Chain Management

Dependency Artifact Supply Chain Management makes release provenance explicit and fail-closed. Release artifacts require dependency lockfiles, SBOMs, vulnerability/license gates, SHA-256 artifact manifests, provenance containing commit + CI run, signatures, and digest-pinned container bases.

## Offline archive constraint
This archive cannot resolve npm/PyPI or OCI registries. It therefore **does not fabricate** `pnpm-lock.yaml`, `uv.lock`, or image digests. Offline validation verifies policy, provenance shape, artifact hashing, exception governance, and release blocking behavior. The `--release` gate intentionally fails until a networked trusted release job generates/verifies those materials.
