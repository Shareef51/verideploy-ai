# Real-Time Release Risk Screen

The authenticated Next.js `/release-risk` workspace consumes only the NestJS public BFF. Recent assessments populate the release selector. New assessments carry actual changed-file metadata and are queued through the existing Kafka release-risk command path. The gateway consumes `verideploy.events.release-risk.v1` and exposes tenant-filtered SSE for the selected assessment.

Two AG Grid views present persisted changed files and authoritative risk factors. Live factor reconciliation snapshots AG Grid filter and column state, applies add/update/remove transactions keyed by factor code, then restores the filter/column state. This prevents live scoring events from resetting user sort/filter analysis.

Risk score, decision, confidence, review requirement, stale-stream state, evidence rationale, and CSV/JSON export are derived from authoritative assessment state. High-risk review links into the existing Human in the Loop Approval queue.
