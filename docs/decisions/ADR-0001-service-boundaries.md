# ADR-0001: Purposeful service boundaries
Status: Accepted
Date: 2026-08-16

## Decision
Use Next.js for the production web application, NestJS for the public BFF/API/realtime/security boundary, and Python FastAPI/workers for AI execution. Kafka separates durable commands/events. PostgreSQL, Redis, and S3-compatible storage are shared platform dependencies.

## Rationale
This keeps security and browser contracts in one TypeScript boundary while preserving Python's AI ecosystem. It prevents the browser from bypassing authorization by reaching Python directly and avoids premature microservice fragmentation.

## Consequences
Cross-language contracts must be versioned and tested. Async workflows require idempotency and durable events. The operational footprint is larger than a single-process prototype but matches the target production architecture.
