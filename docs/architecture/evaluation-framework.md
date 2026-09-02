# Evaluation Framework Foundation

Evaluation Framework establishes the production evaluation control plane used by later VeriDeploy quality milestones.

## Architecture

`versioned JSONL dataset -> dataset manifest/hash -> runner -> evaluators -> case results -> SQLite result store -> baseline comparison -> JSON report/CI gate`

The foundation deliberately separates four contracts:

1. **Dataset contract** — immutable case IDs, semantic dataset versions, category labels, inputs, expected outputs, and metadata.
2. **Runner contract** — a callable accepting one typed evaluation input and returning a structured output. Later milestones can adapt live RAG, LangGraph, visual, release-risk, or RCA pipelines without changing storage/evaluator contracts.
3. **Evaluator contract** — independent evaluators return normalized `[0,1]` scores, pass/fail state, and diagnostic details.
4. **Run contract** — every run captures dataset hash/version, evaluator names, runner identity, seed, Python/platform details, dependency fingerprint, Git revision/dirty state, timestamps, aggregate score, and per-case results.

## Result storage

The default local/CI store is SQLite at `artifacts/evaluation/results.sqlite3`. It is intentionally dependency-free and transactional. The repository interface is isolated so a later production Postgres sink can replace it without changing evaluation semantics.

## Baselines

A completed prior run of the same dataset can be compared to the candidate run. A configurable tolerance controls regression classification. CI uses `--fail-on-regression` when a baseline exists.

## Smoke evaluation

Run locally:

```bash
PYTHONPATH=src python -m verideploy.evaluation.cli smoke
```

Run through the worker boundary:

```bash
PYTHONPATH=src python workers/evaluation/main.py --dataset evals/datasets/smoke/v1.jsonl
```

The smoke dataset is synthetic and deterministic; it makes no paid model calls and exists to validate evaluation plumbing and reproducibility.
