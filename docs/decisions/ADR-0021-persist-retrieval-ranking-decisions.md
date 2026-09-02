# ADR-0021 — Persist retrieval ranking decisions

Status: Accepted.

Retrieval Pipeline Orchestration stores immutable run metadata and normalized stage decisions instead of relying on ephemeral logs. Each decision records stage, candidate identity, input/output score, action, reason, transparent score components, and source version. This supports deterministic ranking reconstruction without rerunning embeddings or model calls.
