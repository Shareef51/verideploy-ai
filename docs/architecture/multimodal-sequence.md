# Multimodal Intake Sequence

```text
Browser
 | multipart file
 v
NestJS /api/v1/ingestion/{modality}
 |-- temporary disk spool
 |-- configured size limit
 |-- signature detection / modality allowlist
 |-- SHA-256
 |-- S3 PutObject
 v
MinIO / S3
 |
 +--> Kafka verideploy.commands.ingestion.v1
 |
 v
 Python ingestion worker
 |-- schema validation
 |-- idempotent job persistence
 |-- atomic lifecycle + event journal
 v
 PostgreSQL + verideploy.events.ingestion.v1

Browser -> NestJS GET /ingestion/jobs/{id}
NestJS -> private FastAPI -> tenant-scoped authoritative job
```

The upload request is not held open for modality-specific AI processing. Multimodal Sequence returns after secure object storage and durable command enqueue.
