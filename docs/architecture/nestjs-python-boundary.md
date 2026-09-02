# NestJS Public API and Python AI-Service Boundary

## Boundary
Browser traffic terminates at Next.js/NestJS. The Python AI service is private network-only and exposes `/internal/v1/*` to trusted services. NestJS centralizes those calls in `PrivateAiClient`; direct module-level `fetch()` calls to Python are prohibited.

## Service authentication
The gateway signs `METHOD + path/query + tenant + correlation + timestamp + body` with HMAC-SHA256. FastAPI validates service identity, timestamp skew, and signature. Staging/production force signature verification even if the compatibility toggle is false. Test/development can retain older route-level guards when no signature is supplied.

## Contracts
Public REST is described by `contracts/openapi/gateway.yaml`. The contract deliberately contains no `/internal/*` path. Private FastAPI OpenAPI remains the internal contract. Public errors use `{error:{code,message,status,correlation_id,details}}`.

## Idempotency and pagination
Asynchronous mutations retain deterministic resource IDs derived from tenant + idempotency key. Approval decisions are version-guarded and are never transparently retried. Investigation pages use an opaque cursor with bounded page size.

## Upload handoff
`POST /api/v1/ingestion/uploads/handoff` creates a deterministic job and short-lived signed object-store PUT URL. Completion performs HEAD verification of size, MIME type and SHA-256 metadata before Kafka processing is queued. The handoff points to object storage, never to FastAPI.
