# ADR-0030: Persisted events are authoritative for live agent execution

## Decision
Render Live Agent Execution Screen exclusively from durable LangGraph Production Runtime events. Client state may cache an authoritative projection but may not synthesize running/completed/tool/model states. Tool payloads are sanitized server-side. No Live Agent Execution Screen database is introduced.
