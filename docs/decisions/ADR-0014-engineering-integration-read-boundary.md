# ADR-0014 — Engineering Integration Read Boundary

## Status
Accepted

## Decision
External engineering systems are accessed through explicit read-only adapters behind a shared outbound policy. The adapter layer owns endpoint allowlisting, credentials, pagination, retries, quotas, and provider response normalization. Agent and MCP layers may request an authorized operation but may not supply credentials, arbitrary hosts, or generic URLs.

Unconfigured and failed integrations are first-class states. They must not be converted into an empty successful result because doing so changes workflow truth.

## Consequences
- MCP Secure Gateway GitHub MCP reads inherit Real Engineering Data Integrations host/retry/quota/secret controls.
- Provider-specific pagination remains inside adapters.
- Outbound write APIs remain outside Real Engineering Data Integrations.
- Synthetic data implements the same result contract but is clearly labeled and cannot masquerade as live data.
