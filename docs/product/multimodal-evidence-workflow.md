# Multimodal Evidence Workflow

## Scope

Multimodal Sequence establishes one production intake pipeline for documents, images, audio, and video. It deliberately stops at a durable `READY` state. Visual reasoning, transcription, keyframe extraction, retrieval, and LangGraph orchestration remain assigned to later milestones.

## Production flow

1. Next.js submits multipart evidence only to the NestJS public gateway.
2. NestJS writes the upload to an OS-managed temporary file instead of retaining large media in heap memory.
3. The gateway enforces a per-modality byte limit, reads the file signature, and rejects a modality/MIME mismatch.
4. The gateway calculates SHA-256 from the bytes and derives a tenant/job-scoped S3 object key.
5. The accepted object is streamed to S3-compatible storage (MinIO locally).
6. Only after storage succeeds does the gateway publish `verideploy.commands.ingestion.v1`.
7. The ingestion worker schema-validates the command and idempotently persists the ingestion job.
8. Lifecycle state and sequenced events advance atomically: `ACCEPTED -> STORED -> PROCESSING -> READY`.
9. NestJS exposes an authoritative status read through the private FastAPI boundary; the browser polls until terminal state.
10. If Kafka enqueue fails after upload, the gateway makes a best-effort delete of the just-written object. Bucket lifecycle policy is the secondary orphan control.

## Security properties

- file type is determined from content signature rather than trusting filename or browser Content-Type;
- original filenames are reduced to safe basenames for object keys;
- SHA-256 is calculated before enqueue and persisted with the object reference;
- object keys are tenant-scoped and never exposed as local filesystem paths;
- private job reads require service identity plus tenant ID;
- cross-tenant job lookup returns not found;
- upload limits are independently configurable for document, image, audio, and video;
- processing commands and events are versioned contracts;
- invalid commands are rejected without creating job state.

## Milestone boundary

`READY` means that secure intake and orchestration completed and the object is ready for the modality-specific pipeline. It does **not** claim OCR, image reasoning, transcription, video frame extraction, or RAG has happened.
