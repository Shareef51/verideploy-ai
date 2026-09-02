# ADR-0029 — Authenticated Next.js App Router with a Gateway-Only Browser Boundary

**Status:** Accepted

## Decision

All production product routes are hosted beneath an authenticated Next.js App Router route group. Authentication is verified server-side from a signed session cookie. Client code receives only verified session claims. Every browser API request goes through a single NestJS gateway client and only targets `/api/v1/*`; private FastAPI routes remain unreachable from browser source.

TanStack Query is the standard server-state cache, Zod is the runtime response-validation boundary, Tailwind/shadcn-compatible primitives provide the reusable design system, and SSE/WebSocket adapters may connect only to the NestJS gateway.

## Why

Earlier cumulative milestones correctly preserved the network boundary but duplicated tenant IDs, users, gateway URLs, error handling and `fetch()` behavior in individual pages. That was acceptable for proving backend workflows but not for a production frontend. Centralizing these concerns removes identity drift, prevents accidental Python-service exposure, and creates a predictable base for Real Time Release Risk Screen+ real-time product screens.

## Consequences

- Public route URLs remain stable because App Router route groups are pathless.
- A valid signed session is mandatory for all product pages.
- Production has no development authentication fallback.
- Product pages cannot own direct network calls or hard-coded tenant/user identities.
- CI must execute a dependency-aware Next.js production build and Playwright shell suite.
- This milestone does not introduce a new identity provider; it defines the verified-session contract expected from the configured authentication boundary.
