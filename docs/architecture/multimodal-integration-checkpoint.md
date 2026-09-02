# Multimodal Integration Checkpoint

This checkpoint hardens the existing image, document/PDF, audio, and video pipelines without introducing a second multimodal stack.

## Invariants

- Large fixtures are tested at policy boundaries using deterministic logical work units; tests never allocate hundreds of MB just to prove limits.
- Image/PDF/audio/video processing has explicit work caps and timeline caps.
- Redaction occurs before persisted derivative hashing/storage references are produced.
- Storage keys are tenant scoped and content derivatives carry SHA-256 digests.
- Every successful or degraded evidence item receives a deterministic trace ID.
- Partial modality failures degrade explicitly and may fuse only when the configured surviving-evidence ratio is met.
- Dropped/degraded evidence is never silently omitted from lineage.

## Gate

`PYTHONPATH=src python scripts/validate_multimodal.py`

The gate requires all four modalities, clean-path fusion, bounded partial-failure fusion, 100% traceability, and 100% redaction correctness.
