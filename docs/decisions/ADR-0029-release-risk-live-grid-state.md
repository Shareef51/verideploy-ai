# ADR-0029 — Preserve analytical grid state during live release-risk updates

## Decision
Use stable AG Grid row IDs and transactions for live factor updates. Capture and restore filter and column state around reconciliation. Never replace the entire screen or reconstruct user filters from server events.

## Rationale
Release-risk events are authoritative data changes; sort/filter state is user-owned presentation state. Keeping the two concerns separate satisfies deterministic realtime behavior and prevents live events from disrupting active review.
