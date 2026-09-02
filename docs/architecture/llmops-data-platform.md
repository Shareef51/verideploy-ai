# LLMOps Data Platform

Append-only, tenant-isolated normalized LLMOps facts are keyed by correlation ID and lineage IDs. Payloads are redacted before persistence; retention class is stored per event. The correlation trace aggregates model, prompt, token, cost, latency, retrieval, tool, retry, failure, and confidence data without duplicating business outputs.
