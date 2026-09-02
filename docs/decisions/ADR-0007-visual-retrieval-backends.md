# ADR-0007 — Visual retrieval backend abstraction

**Status:** Accepted

## Decision
Use a backend-neutral visual retrieval interface. Support Hugging Face-native ColPali as the high-fidelity optional backend and a deterministic CPU fallback for local/test environments.

ColPali embeddings are stored by reference because their late-interaction multi-vector semantics should not be collapsed into the single-vector pgvector table. The CPU fallback stores a small feature vector directly in PostgreSQL.

## Consequences
- Production deployments with suitable hardware can enable ColPali without changing API contracts.
- CI/local environments can render/index/search without downloading multi-billion-parameter models.
- Benchmark reports always name the backend so fallback results cannot be misrepresented as ColPali results.
