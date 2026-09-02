# Video Evidence Pipeline

Video Evidence Pipeline turns an admitted video object into traceable multimodal incident evidence without placing large media payloads on Kafka.

## Production flow

`S3/MinIO video object -> Kafka object-reference command -> video-evidence-worker -> FFprobe validation/duration -> FFmpeg WAV extraction -> audio transcription -> FFmpeg scene + interval keyframes -> CPU-safe frame observations -> transcript/frame alignment -> PostgreSQL/RLS -> progress/result events`

## Key decisions

- Kafka transports object references only; video bytes never ride the event bus.
- Worker-side validation re-checks the MP4 signature, byte limit, SHA-256, and FFprobe duration even though Multimodal Sequence already admitted the object.
- Scene-change keyframes use FFmpeg `showinfo` `pts_time`; no approximate timestamps are assigned.
- Interval frames guarantee temporal coverage when scene detection is sparse.
- The CPU frame analyzer emits direct visual signatures only (luminance/edge density) and explicitly does not claim semantic root-cause interpretation.
- Audio Transcription Pipeline transcript evidence remains authoritative for spoken statements.
- Cross-modal alignment is a distinct timeline event and stores the alignment delta; it is not represented as direct observation.
- Partial modality failure yields `PARTIAL` when useful evidence survives. The job fails only when both transcript and frame evidence are unavailable.
- Frame, job, and timeline IDs are deterministic so retries do not duplicate evidence.

## Timeline evidence kinds

- `frame_observation` — direct information extracted from a frame.
- `transcript_statement` — redacted timestamped Audio Transcription Pipeline speech evidence.
- `cross_modal_alignment` — a deterministic temporal association between a transcript segment and the nearest frame within policy.

## Security and tenancy

`video_evidence_jobs`, `video_keyframes`, and `video_timeline_events` use explicit tenant predicates plus forced PostgreSQL RLS. The private read endpoint accepts only trusted internal service identities.

## Limits

Video Evidence Pipeline does not perform semantic video RCA. Later agents may reason over this evidence, but they must preserve the direct-observation/inference distinction and stable evidence identifiers.
