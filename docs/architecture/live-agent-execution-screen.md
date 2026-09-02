# Live Agent Execution Screen

The screen is an authoritative projection of persisted `graph_runtime_events`. It never infers node execution from browser timers. It exposes node status/duration/retries, sanitized tool calls, model role/token/cost telemetry, ordered events, and failure drill-down through Next.js → NestJS → private FastAPI. Reconnect uses ordered replay followed by authoritative refresh.
