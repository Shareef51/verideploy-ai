# Multimodal RAG Fusion Verification

Run:

```bash
PYTHONPATH=.:src pytest -q tests/unit/test_multimodal_fusion.py
PYTHONPATH=.:src python scripts/benchmark_multimodal_fusion.py
PYTHONPATH=.:src pytest -q
python -m compileall -q src services workers scripts
```

The benchmark gate requires all three seeded channels (`text`, `visual`, `runtime`) to contribute, 100% contributing-channel citation coverage, and zero duplicate selected evidence IDs.

Multimodal RAG Fusion itself does not require a live OpenAI call or a live external runtime telemetry source. PostgreSQL-dependent integration tests inherited from Milestones 12–14 remain conditional on `TEST_POSTGRES_URL`.
