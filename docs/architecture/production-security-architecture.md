# Production Security Architecture

VeriDeploy uses two separate identity planes. Browser/API traffic authenticates with OIDC Authorization Code + PKCE and derives user, tenant and role context from verified token claims. Private service traffic never accepts browser identity as service identity; NestJS and trusted workers sign private FastAPI requests with service identity and bounded clock skew.

## Authorization
The canonical policy is `config/security/policy.json`. Authorization is default-deny. RBAC grants action families while ABAC can narrow access by environment/service/team. The authenticated tenant claim is authoritative; client-supplied tenant/user headers are overwritten at the gateway.

## Browser and API controls
The gateway enables restrictive CSP, anti-framing, no-sniff, referrer and permissions policies, explicit CORS allowlists, HSTS in production, same-origin CSRF rejection for cookie-bearing unsafe methods, and OIDC JWT validation. OIDC accepts RS256 only and validates issuer, audience, expiry, issue time, subject, tenant and roles. PKCE uses S256.

## SSRF
Outbound integration URLs are parsed before use. Schemes and hosts are allowlisted; embedded credentials are denied; loopback, private, link-local, multicast, reserved and unspecified addresses are denied, including DNS-resolved destinations when network resolution is enabled. Redirects are disabled by policy.

## Secrets and encryption
Production configuration must reference an external secret manager (`aws-sm://`, `azure-kv://`, `gcp-sm://`, or `vault://`). The architecture requires KMS-backed at-rest encryption, TLS for PostgreSQL, object-store server-side encryption, and TLS 1.2+ in production. Local `.env` values are development-only and are not a production secret mechanism.

## Network
Kubernetes starts with default deny. Explicit policy permits web → gateway and gateway → private AI service; production manifests must add only the minimum egress required for databases, brokers, telemetry and approved external APIs.

## Supply chain
CI runs the normal test/lint/build suite and the Production Security Architecture security architecture scan. Policy allows zero unresolved critical and zero unresolved high dependency vulnerabilities. Lockfiles and pinned container images remain part of the build contract. Production image/SBOM/CVE tooling can plug into this policy without changing application authorization semantics.

## Gate
`PYTHONPATH=src python scripts/security_scan.py` fails when a critical architecture control is missing. Security tests exercise PKCE, RBAC/ABAC/tenant isolation, SSRF blocks, secret references, encryption posture and the repository architecture scan.
