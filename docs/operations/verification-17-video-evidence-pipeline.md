# Video Evidence Pipeline Verification

Video Evidence Pipeline verification must cover real FFmpeg behavior, deterministic replay, degradation, persistence contracts, and the cumulative suite.

Required checks:

- generate a small synthetic MP4 with audio and scene changes;
- FFprobe duration/stream discovery;
- FFmpeg WAV extraction;
- exact scene `pts_time` recovery;
- interval keyframe coverage;
- deterministic frame/event identifiers on replay;
- transcript/frame alignment and ordered timeline sequence;
- silent video degrades to frame-only `PARTIAL`;
- missing transcription configuration degrades without losing frame evidence;
- duration policy rejection;
- Kafka command contains object reference, not video bytes;
- migration upgrade/downgrade DDL contains all Video Evidence Pipeline tables and forced RLS;
- private read endpoint enforces service identity and tenant scope;
- full cumulative test suite.

Live Docker/Kafka/MinIO/PostgreSQL execution is not claimed unless those runtimes are actually available.
