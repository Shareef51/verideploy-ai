# Next.js Production Frontend Foundation Verification

## Repeatable source gate

```bash
make frontend-foundation-validate
```

The validator checks the protected App Router layout, signed-session implementation, production bypass policy, route migration, centralized network access, gateway/Python boundary, session-derived identity, TanStack Query, Zod, Tailwind/shadcn setup, realtime clients, error boundaries, accessibility, Playwright source coverage and absence of mock-only product copy.

## Python regression

```bash
PYTHONPATH=src:. pytest -q
```

This includes static/source contract tests for the frontend foundation as well as all cumulative backend tests.

## Dependency-aware frontend gate

In a connected/provisioned environment:

```bash
corepack enable
pnpm install --no-frozen-lockfile
pnpm --filter @verideploy/web typecheck
pnpm --filter @verideploy/web build
pnpm --filter @verideploy/web exec playwright install --with-deps chromium
FRONTEND_SESSION_SECRET=replace-with-test-secret pnpm --filter @verideploy/web test:e2e
```

The current execution container cannot resolve `registry.npmjs.org` (`EAI_AGAIN`), so dependency installation, `next build`, dependency-aware TypeScript typechecking and Playwright browser execution cannot be claimed locally. Syntax transpilation and source-contract validation are separate checks and must not be represented as a production build.

## Authentication configuration

Production must set a high-entropy `FRONTEND_SESSION_SECRET` and keep `FRONTEND_DEV_AUTH_BYPASS=false`. A session payload must contain `userId`, `tenantId`, non-empty `roles`, `displayName`, and a future `expiresAt`, then be HMAC-SHA256 signed in the `payload.signature` cookie format.
