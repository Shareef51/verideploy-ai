# Five Polished Production Demos

Five Polished Production Demos adds five one-click synthetic scenarios: release risk, incident RCA, screenshot, architecture PDF, and incident recording. Each launch enters the existing NestJS public boundary. Release risk publishes the production release command. RCA publishes the production investigation command. Multimodal demos first pass through production ingestion/object storage/Kafka, then launch a durable investigation. The browser receives only accepted identifiers and uses existing live/replay workspaces for authoritative state. No demo mutates the database directly.

## Synthetic-data invariant

Every fixture is committed under `data/demos/` and the UI displays `SYNTHETIC DATA ONLY`. No production telemetry or customer information is required.
