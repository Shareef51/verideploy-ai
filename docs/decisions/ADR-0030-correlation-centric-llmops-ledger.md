# ADR-0030 — Correlation-centric LLMOps ledger

Use correlation ID as the cross-system trace key while preserving graph/agent/retrieval/tool IDs as lineage references. Store normalized operational facts only; never raw secrets. Records are append-only and RLS-protected.
