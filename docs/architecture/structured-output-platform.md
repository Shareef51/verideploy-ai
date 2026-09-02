# Structured-Output Platform

## Purpose

Structured Output Platform establishes one authoritative boundary between model-generated text and typed VeriDeploy business data. Provider-side Structured Outputs reduce malformed responses, but Pydantic validation remains mandatory before a result is returned to business logic or persisted as a successful structured result.

## Flow

```text
AIRequest
 -> StructuredSchemaRegistry(name@version)
 -> Pydantic JSON Schema export
 -> OpenAI Responses text.format json_schema / strict=true
 -> AIResult.output_text
 -> syntax-only JSON unwrap (optional)
 -> Pydantic strict validation
 -> accepted: persist validated response + typed model
 -> rejected: telemetry + bounded fresh provider retry
 -> exhausted: StructuredOutputValidationError
```

## Registry

`StructuredSchemaRegistry` owns schema name/version/model mappings. Schema names and versions are explicit so historical runs can resolve a stable contract. The registry exports:

- provider-facing JSON Schema under `contracts/structured-output/`;
- a manifest of exported schemas;
- deterministic TypeScript aliases under `packages/contracts/src/generated/structured-output.ts`.

Object schemas are closed with `additionalProperties: false` recursively.

## Validation and repair policy

The platform does not invent missing fields or coerce incorrect business types. Local repair is intentionally limited to extracting otherwise-valid JSON from common wrappers such as Markdown code fences or surrounding prose. If the extracted JSON still fails Pydantic validation, the platform can issue a bounded fresh provider request. Provider retry count is capped by `StructuredOutputRepairPolicy`.

Validation errors are sanitized before telemetry: field locations, error types, and short messages are retained; raw model output is not copied into validation telemetry.

## Persistence ordering

Responses API Adapter response persistence is deferred when `structured_output` is set by the Structured Output Platform engine. The gateway exposes `persist_validated_response`, and the engine invokes it only after strict Pydantic validation succeeds. Invalid structured outputs therefore cannot be stored as accepted structured results.

## Discriminated unions

The built-in schemas demonstrate tagged unions for both evidence findings and proceed/escalate decisions. Pydantic discriminators are preserved in exported JSON Schema, allowing the same variant contract to be enforced in Python, provider constraints, and generated TypeScript.

## Built-in schemas

- `evidence_extraction@1.0.0`
- `structured_decision@1.0.0`

These are platform foundation contracts. Later agent/RAG milestones can register additional schemas without bypassing this validation boundary.
