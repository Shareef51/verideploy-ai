# ADR-0009 — Transcribe object references, not Kafka audio payloads

## Decision

Kafka transcription commands contain S3-compatible object references, not audio bytes. The worker retrieves the object from authorized storage and revalidates it before transcription.

## Rationale

Audio uploads can be large. Putting binary audio on Kafka would create broker/message-size coupling, duplicate storage, and operational failure modes. Object references preserve the durable Multimodal Sequence ingestion boundary while keeping Kafka messages small and replayable.

## Consequences

The worker requires object-store access and must treat retrieved bytes as untrusted. Retries reuse deterministic transcription/segment identities, so replay cannot duplicate transcript evidence.
