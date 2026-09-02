# ADR-0008 — Video evidence uses object references and deterministic time-aligned evidence

## Status
Accepted

## Context
Videos can be hundreds of megabytes and contain independent audio and visual evidence streams. Sending raw media through Kafka or assigning approximate frame times would make the system operationally unsafe and evidentially weak.

## Decision
1. Kafka commands contain only authorized S3/MinIO object references.
2. FFprobe/FFmpeg run in the multimodal worker image; FFmpeg is installed explicitly in the production AI container.
3. Scene timestamps come from FFmpeg `showinfo pts_time`; interval timestamps are deterministic scheduled times.
4. Extracted audio reuses the Audio Transcription Pipeline transcription service.
5. Frames have stable evidence IDs and direct CPU-safe observations.
6. Transcript/frame alignment is deterministic and represented as a separate event with a measured time delta.
7. Useful surviving modality evidence produces `PARTIAL`; both modalities failing produces `FAILED`.

## Consequences
The pipeline is replay-safe, traceable, and resilient to one modality failing. Semantic frame interpretation can be upgraded later behind the frame-analysis contract without changing timeline or persistence contracts.
