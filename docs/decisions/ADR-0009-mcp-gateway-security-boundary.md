# ADR-0009 — Centralize MCP authorization at the secure gateway

**Status:** Accepted

MCP tools are model-controlled, but authorization, tenant scope, risk acceptance, and human approval are not model decisions. VeriDeploy therefore routes every MCP invocation through a central gateway before any adapter executes. Tool servers remain thin protocol surfaces around the same registry and gateway.

External writes are disabled by default. A high-risk write requires both an explicitly enabled deployment policy and a non-empty approval reference. Tool output is sanitized and schema-validated after execution. Denied/injected calls are audited with argument hashes rather than raw input.

This preserves one policy path across internal HTTP invocation and official MCP transports and reduces confused-deputy/tool-injection risk.
