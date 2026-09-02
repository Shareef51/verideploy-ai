# 500-Case Evaluation Dataset

500 Case Evaluation Dataset turns the Evaluation Framework evaluation control plane into a substantial, deterministic benchmark corpus for VeriDeploy AI. All cases are synthetic and are safe for local, CI, and portfolio demonstrations.

## Dataset contract

The canonical dataset is `evals/datasets/verideploy-500/v1.jsonl` with dataset id `verideploy-500` and semantic version `1.0.0`.

| Category | Cases | Primary quality target |
| --- | ---: | --- |
| retrieval | 100 | relevant evidence retrieval and top-k coverage |
| rca | 80 | root-cause identification from correlated evidence |
| release_risk | 80 | deploy/review/hold decision quality |
| visual | 60 | image-grounded observation and numeric tolerance |
| document_qa | 60 | policy/document answers with citation spans |
| hallucination | 60 | supported-vs-unsupported claim discipline |
| citation | 60 | claim-to-source attribution completeness |
| **Total** | **500** | |

Every case contains a stable `case_id`, category, model input, an explicit `ground_truth` object, non-empty `source_requirements`, and provenance metadata declaring the case synthetic and evaluation-only.

## Quality gates

`verideploy.evaluation.quality` enforces the exact 500-case/category contract and fails closed on duplicate semantic content, label leakage fields or markers, missing ground-truth fields, missing source requirements, source/ground-truth contract mismatches, unsupported categories, or invalid split/provenance metadata.

Run locally:

```bash
PYTHONPATH=src python scripts/validate_dataset.py
```

Regenerate deterministically:

```bash
PYTHONPATH=src python scripts/generate_dataset.py
```

The manifest records the SHA-256 of the JSONL source. Dataset content, rather than generation timestamps, is the reproducibility anchor.

## Leakage policy

Evaluation inputs must never contain `ground_truth`, `answer_key`, `expected_answer`, or `gold_label` fields, and cannot contain reserved answer markers. Ground truth exists only in evaluator-visible fields. This prevents a runner from succeeding by reading labels embedded in the prompt.

## Source contract

Each category specifies concrete source ids and source types (runbook, incident, trace, metric, deployment, code diff, CI run, image, PDF, or log). Ground-truth source ids must be a subset of required sources, allowing later metric milestones to measure retrieval, citation, and evidence coverage against the same corpus.
