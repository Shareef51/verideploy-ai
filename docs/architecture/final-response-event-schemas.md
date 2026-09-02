# Final Response and Event Schemas

Final Response Event Schemas establishes one versioned contract surface for the terminal release-risk and incident-RCA responses and for the real-time envelopes that transport those results.

## Canonical contracts

The source of truth is `src/verideploy/contracts/final_schemas.py`. The generator emits JSON Schema documents under `contracts/final/`, Python client types under `generated/clients/python/`, and TypeScript client types under `generated/clients/typescript/`.

The finalized families are: release-risk response, RCA response, evidence reference, citation reference, timeline entry, review response, API error, WebSocket envelope, and Kafka envelope. Terminal risk/RCA responses require citations that resolve to evidence IDs. The WebSocket envelope carries an authoritative high-watermark and cannot report a sequence greater than it. Kafka events include the same final payload plus tenant, aggregate, ordering, correlation, causation, trace, retry, and schema metadata.

## Backward compatibility

`contracts/compatibility/final-response-event-schemas-baseline.json` stores a compatibility signature. CI rejects removal of existing properties or schema definitions, addition of new required properties, incompatible type/format/reference/const changes, and enum narrowing. Additive optional fields and enum widening remain compatible with v1 consumers.

Breaking changes require a new schema major version and parallel contract family; the v1 snapshot is never rewritten merely to make CI green.

## Client generation

Run:

```bash
PYTHONPATH=src python scripts/generate_contracts.py
PYTHONPATH=src python scripts/validate_event_contracts.py
```

Generated files are deterministic and covered by the monorepo integrity manifest.

## Runtime boundaries

- OpenAPI exposes final response/error/WebSocket component schemas.
- AsyncAPI exposes `verideploy.events.final.v1` using the final Kafka envelope.
- Browser and gateway clients consume the generated TypeScript contract definitions.
- Python workers/services can use the canonical Pydantic models or generated Python client types.

No contract embeds raw secrets, credentials, or untrusted tool instructions.
