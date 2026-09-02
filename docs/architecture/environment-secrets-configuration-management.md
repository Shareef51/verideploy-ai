# Environment, Secrets, and Configuration Management

## Contract

VeriDeploy now uses a versioned environment manifest plus per-environment overlays. Server configuration is validated on startup; staging/production require explicit infrastructure endpoints and identity settings. Secret values remain server-side and production secret material is supplied by an external secret controller/provider.

## Secret lifecycle

Production deployments reference managed secrets rather than committing values. The policy defines a 90-day maximum rotation age, 24-hour grace window, dual-read rotation support, and mandatory audit events. Kubernetes uses External Secrets Operator-compatible resources to refresh the runtime Secret.

## Browser boundary

Only variables listed in `publicVariables` may use the `NEXT_PUBLIC_` namespace. CI statically scans browser-capable TypeScript/TSX modules for access to any secret variable. Server-only modules use `server-only`.

## Fail-fast

Python Pydantic settings and NestJS/web server config loaders reject missing or malformed production configuration before accepting traffic. Secret-safe log helpers recursively redact credential-bearing fields.
