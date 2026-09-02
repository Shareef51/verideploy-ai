# Synthetic Incident Dataset

Synthetic Incident Dataset adds a deterministic NexusPay incident corpus for evaluation, demos, retrieval, and future model/agent testing. The corpus is derived from the NexusPay Service Topology and uses stable UUIDv5 identities and content hashes.

## Dataset contract

The checked-in corpus contains 240 incidents: 30 examples for each of eight failure modes. Every incident includes a production release, metric series, logs, traces, an ordered timeline, an explicit resolution, a trigger, and a root-cause label. Each observable modality contains both causal evidence and non-causal noise so downstream evaluations must reason over evidence rather than rely on a single perfectly clean signal.

## Leakage controls

Machine-readable failure-mode strings are forbidden from observable feature text. Incident families are split deterministically into train, validation, and test partitions with no family overlap. The validator also checks label balance, unique IDs, hashes, topology references, time ordering, modality coverage, and deterministic reproduction.

## Persistence

`synthetic_incidents` stores one tenant-scoped JSON payload per incident plus indexed label/split/service/time columns and an incident SHA-256. PostgreSQL RLS is enabled and forced. Seeding is idempotent by stable incident ID.
