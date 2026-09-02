# RuntimeEvidenceAgent

## Boundary
Runtime Evidence Agent queries authorized runtime telemetry and normalizes it into the Multimodal RAG Fusion `RuntimeEvidenceInput` contract. It does not perform RCA or make remediation decisions.

## Sources
- Prometheus: read-only `/api/v1/query_range` for active and baseline windows.
- Grafana: read-only annotations API with enforced service/environment tags.
- Loki: read-only `/loki/api/v1/query_range`.
- Tempo-compatible trace search: read-only `/api/search`.

Live model-generated queries must explicitly contain trusted service and environment scope for Prometheus, Loki, and trace search. Grafana scope is injected as tags. All timestamps are normalized to UTC before source execution.

## Reproducibility
The active window is immutable once authorized. The baseline is the immediately preceding non-overlapping window of `baseline_minutes`. Source failure never shifts either window. Synthetic mode is deterministic for the same service, environment, query, and source.

## Failure semantics
Each source has an independent execution record. One failed source produces a `runtime_source_failure` limitation while successful sources remain usable. All-source failure is explicitly insufficient.

## Evidence
Metric, log, trace, and Grafana annotation results are normalized to Multimodal RAG Fusion runtime evidence with stable evidence IDs, source system/ID, observed timestamp, service/environment, and confidence.
