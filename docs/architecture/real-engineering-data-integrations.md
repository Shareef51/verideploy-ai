# Real Engineering Data Integrations

Real Engineering Data Integrations adds production read adapters for GitHub, Jira Cloud, Prometheus, Grafana annotations, distributed traces (Tempo/OpenTelemetry data), and Loki logs. The adapters sit below MCP Secure Gateway's MCP gateway and Runtime Evidence Agent's runtime-evidence contracts; they do not authorize users or decide workflow truth.

## Security boundary

All outbound HTTP reads use `ResilientReadClient`. A configured endpoint must use HTTP(S), must not contain userinfo credentials, and its hostname must appear in `INTEGRATION_ALLOWED_HOSTS`. Redirect targets are revalidated before following. The client is GET-only for Real Engineering Data Integrations.

Credentials are supplied only as server-side adapter headers and are never accepted in tool/model arguments or copied into `IntegrationResult` records. GitHub uses Bearer token headers. Jira supports `basic` (Atlassian email + API token) and `bearer` (OAuth access token) modes.

## Reliability controls

Every integration call receives a fresh request budget. Pagination and retries consume that same budget. This avoids a process-lifetime quota bug and makes concurrent integration calls independent.

Retryable responses are limited to transient statuses (408, 409, 425, 429, 5xx) plus GitHub-style rate-limited 403 responses. Authentication/authorization 4xx responses are not retried. `Retry-After` and `X-RateLimit-Reset` are honored only when the required delay is within `INTEGRATION_MAX_RETRY_DELAY_SECONDS`; otherwise the call fails clearly rather than retrying before the provider's reset time.

## Pagination

- GitHub follows the provider `Link` header and stops at `max_pages` and the request budget.
- Jira Cloud `/rest/api/3/search/jql` follows `nextPageToken` and `isLast` with the same bounds.
- Prometheus, Grafana, Tempo, and Loki use bounded time-range requests and response limits rather than unbounded pagination.

## Workflow truth

An absent endpoint or missing credential is represented as `IntegrationStatus.UNCONFIGURED`, not as `OK` with zero records. Provider failures are represented as `FAILED`. Therefore downstream workflows can distinguish "source unavailable" from "source queried successfully and returned no matching data".

The private readiness endpoint is `GET /internal/v1/integrations/status`; it reports only configuration booleans and never secrets.

## Synthetic parity

`SyntheticIntegrationBundle` returns the same `IntegrationResult`/`IntegrationRecord` contract and the same six source identifiers as live adapters. Synthetic records are explicitly identified as synthetic and deterministic for the same service/environment/time window.
