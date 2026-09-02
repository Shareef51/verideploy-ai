# VeriDeploy AI production threat model — Production Security Architecture

## Security objectives
Protect tenant evidence, credentials, evaluation data, agent/tool execution, approval records, model metadata and audit traces against cross-tenant access, identity spoofing, prompt/tool abuse, SSRF, secret disclosure and supply-chain compromise.

## Trust boundaries
1. Browser → NestJS public API: OIDC Authorization Code + PKCE; bearer token identity is authoritative.
2. NestJS/workers → private FastAPI: signed service identity with bounded timestamp skew; browser credentials are not service credentials.
3. Application → PostgreSQL/Redis/Kafka/object store: private network policy, tenant-scoped application access, encryption requirements.
4. MCP/integrations → external systems: allowlisted hosts, SSRF defense, read-only default, approval for consequential actions.
5. Build → deployment: lockfiles, pinned images, CI tests/scans and zero unresolved critical dependency findings.

## Primary threats and controls
- **OIDC/token forgery:** RS256 only, issuer/audience/time/required-claim checks and JWKS signature verification.
- **Cross-tenant access:** authenticated tenant claim overwrites client headers; RBAC + ABAC + repository/RLS controls remain cumulative.
- **Privilege escalation:** default-deny action policy and explicit roles; high-risk operations still require Human in the Loop Approval approvals and Five Layer Guardrails tool guardrails.
- **CSRF/CORS/browser injection:** explicit origins, same-origin checks for cookie-bearing unsafe methods, restrictive CSP, no framing and secure headers.
- **SSRF/cloud metadata access:** HTTPS + host allowlists, no userinfo, no redirects, deny loopback/private/link-local/reserved targets and DNS rebinding targets.
- **Service impersonation:** signed internal requests, trusted service names and max clock skew; production requires service authentication.
- **Secret disclosure:** production uses external secret-manager references; no credentials in source; observability redaction remains enabled.
- **Data exposure at rest/in transit:** TLS 1.2+ assumptions, database TLS, object-store SSE and KMS-backed at-rest encryption required in production.
- **Network pivoting:** Kubernetes default-deny NetworkPolicy with minimum explicit paths.
- **AI/prompt injection:** Five Layer Guardrails five-layer guardrails treat retrieved content as untrusted and enforce tool/output boundaries.
- **Supply chain:** lockfiles, pinned runtime/container versions, CI security policy and zero unresolved critical/high dependency findings.

## Residual risk
Local Docker Compose intentionally favors developer ergonomics and is not the production network perimeter. Production deployment must terminate TLS at an approved ingress/load balancer, supply external OIDC/secret/KMS providers, enforce the Kubernetes policies, and run dependency/container/SBOM scanners supported by the deployment environment.
