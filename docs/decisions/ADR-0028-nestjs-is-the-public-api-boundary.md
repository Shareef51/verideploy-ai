# ADR-0028 — NestJS is the public API boundary

**Status:** Accepted

Browser code must not address the Python AI service. NestJS owns public REST/BFF behavior, request validation, idempotency semantics, pagination, upload coordination, consistent public errors and service-to-service signing. Python remains a private AI/runtime service. This keeps internal models and service credentials off the browser trust boundary and permits independent AI-service evolution without exposing private contracts publicly.
