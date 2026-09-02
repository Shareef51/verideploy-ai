# ADR-0012 — Runtime evidence time and source boundary

Status: Accepted

Runtime Evidence Agent uses separate read-only source adapters and a common UTC-normalized query contract. The model chooses among registered source contracts but cannot change trusted service, environment, or time scope. Active and baseline windows are computed before source calls and are identical across retries/source failures. Partial source failure degrades explicitly instead of triggering time-window drift or fabricated telemetry. Production source queries must include trusted service/environment scope before network I/O.
