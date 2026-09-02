# Audio Transcription Pipeline

## Scope

Audio Transcription Pipeline turns Multimodal Sequence audio objects into timestamped, tenant-scoped transcript evidence. Kafka carries object references only; audio bytes stay in S3-compatible object storage. The multimodal worker retrieves the authorized object, validates its signature and size again, hashes the bytes, then invokes the configured transcription provider.

## Runtime path

`ingestion object -> audio-transcription Kafka command -> S3/MinIO fetch -> signature/hash validation -> transcription provider -> timestamped segments -> redaction -> atomic persistence -> audio.transcription event`

## OpenAI modes

`TRANSCRIPTION_RESPONSE_MODE=timestamped` uses a timestamp-capable response contract (`verbose_json` + segment timestamps). `TRANSCRIPTION_RESPONSE_MODE=diarized` uses `diarized_json` plus automatic chunking and preserves speaker labels returned by the provider. Model IDs remain configuration-driven through `OPENAI_TRANSCRIPTION_MODEL`.

If the configured provider/model does not return timestamped segments, the request fails. VeriDeploy never fabricates segment times or speaker labels.

## Privacy and lineage

Raw provider transcript text is not stored in the canonical segment table. Each segment stores redacted text plus `raw_text_sha256`. Redaction includes secret patterns and configurable PII regexes. Stable `VD-AUDIO-*` evidence IDs and deterministic segment UUIDs make retry/resume idempotent.

## Persistence

Alembic revision `0004_milestone16_audio_transcription` creates `audio_transcriptions` and `audio_transcript_segments`, with tenant foreign keys, uniqueness constraints, ordered timestamp checks, forced PostgreSQL RLS, and indexes for tenant/status and tenant/transcription sequence access.
