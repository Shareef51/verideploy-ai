# LLM Quality Metrics

LLM Quality Metrics adds a reproducible LLM-output quality layer to VeriDeploy AI without making normal CI depend on a paid or nondeterministic model call.

## Metrics

The deterministic evaluator scores five independent dimensions per case:

- **Answer quality** — token-overlap F1 against the versioned reference answer.
- **Instruction adherence** — required/forbidden terms, output format, and bounded-length constraints.
- **Structured-output validity** — JSON parsing plus required keys, expected primitive types, and allowed values.
- **Refusal/abstention correctness** — whether the system abstains exactly when the evaluation contract requires it, including a non-empty reason for required abstentions.
- **Reasoning-result consistency** — whether the declared intermediate decision/result agrees with the final result. This evaluates structured result labels only; it does not persist or require private chain-of-thought.

Every case stores `model_id`, `prompt_id`, and `prompt_version`, enabling direct variant grouping and baseline deltas. The offline LLM Quality Metrics benchmark uses synthetic behavior profiles solely to validate the comparison machinery; the report labels them explicitly as synthetic and must not be read as real vendor-model performance.

## Optional model judge

Model judging is disabled by default. A judge can run only through a versioned `QualityJudgeSpec` containing judge name, model ID, prompt ID, prompt version, and an exact SHA-256 of the prompt template. Calibration reports MAE, bias, and Pearson correlation against labeled examples and must pass thresholds before the benchmark gate succeeds.

The production principle is: deterministic checks remain the CI source of truth; a calibrated model judge is supplementary evidence.

## Gate

Run locally with:

```bash
PYTHONPATH=src python scripts/benchmark_llm_quality_metrics.py
```

CI fails if the candidate profile falls below any quality threshold, if judge calibration fails, or if the candidate aggregate score regresses below the configured baseline profile.
