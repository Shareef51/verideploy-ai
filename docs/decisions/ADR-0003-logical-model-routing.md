# ADR-0003 — Logical Model Roles Instead of Hard-Coded Model IDs

- **Status:** Accepted
- **Date:** 2026-08-16

## Context

OpenAI model availability and prices change over time. Business code that directly names a model couples release-risk, RAG, RCA, and other workflows to a volatile provider detail and makes governance difficult.

## Decision

VeriDeploy routes workloads to stable logical roles (`fast`, `standard`, `reasoning`). Deployment configuration binds those roles to provider model IDs and optional fallback chains. Pricing is loaded from a versioned catalog. Every resolved model is audited with the routing reason and cost information.

## Consequences

- model changes do not require business-code changes;
- policy and cost changes are reviewable configuration changes;
- production cannot start with unresolved roles;
- production rejects unpriced configured models by default;
- callers may still use the OpenAI AI Gateway explicit-model compatibility path only when no router is installed; normal production execution uses the router.
