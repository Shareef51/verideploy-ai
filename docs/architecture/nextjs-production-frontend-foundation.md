# Next.js Production Frontend Foundation

## Purpose

Next.js Production Frontend Foundation replaces the cumulative page-by-page frontend with a production App Router foundation while preserving the public URLs established in earlier milestones. All product routes live under the `(platform)` route group and inherit one authenticated server layout, one session context, one TanStack Query client, one gateway-only browser client, and one accessible application shell.

## Security and routing boundary

The browser remains constrained to the NestJS Python Boundary NestJS BFF. `gatewayFetch()` accepts only `/api/v1/*` paths and rejects gateway origins containing `/internal/v1` or port `8000`. No product page owns a gateway origin, tenant UUID, user UUID, or raw `fetch()` call.

The authenticated layout verifies the `verideploy_session` cookie on the server with HMAC-SHA256 and constant-time signature comparison. The payload contains tenant ID, user ID, roles, display name and expiry. Missing, invalid or expired sessions redirect to `/sign-in`. `FRONTEND_DEV_AUTH_BYPASS` is permitted only outside `NODE_ENV=production` and defaults to false.

## App Router structure

```text
app/
 layout.tsx
 global-error.tsx
 sign-in/page.tsx
 (platform)/
 layout.tsx
 loading.tsx
 error.tsx
 not-found.tsx
 page.tsx
 release-risk/
 incidents/
 evidence/
 postmortems/
 approvals/
 topology/
 evidence-graph/
 citations/[citationId]/
```

Route groups do not alter URLs, so `/approvals` and `/topology` remain stable while becoming protected by the platform layout.

## Data and realtime foundation

TanStack Query owns server-state caching for read-heavy screens. Zod schemas validate gateway responses before UI rendering. Mutating/streaming workflows use the same session-aware gateway client. Dedicated SSE and WebSocket clients are gateway-scoped and reject private-AI origins.

## Design system

Next.js Production Frontend Foundation adds CSS design tokens, Tailwind v4 configuration, shadcn-compatible `components.json`, and reusable `Button`, `Card`, `Badge`, and `StatePanel` primitives. The overview uses Tailwind responsive grid breakpoints; cumulative workflow-specific styles remain available while screens migrate incrementally onto primitives.

## Accessibility and resilience

The shell includes a keyboard skip link, semantic navigation/main landmarks, visible focus rings, reduced-motion behavior, route loading/error/not-found states and a global error boundary. Empty states are explicit and do not fall back to fabricated frontend data.

## Production gate

`make frontend-foundation-validate` rejects legacy unprotected route directories, direct page `fetch()` calls, hard-coded demo identities, browser references to Python/internal routes, production auth bypass, mock-only product copy, and missing foundation assets. CI additionally runs `pnpm build` and Playwright shell tests in a dependency-provisioned environment.
