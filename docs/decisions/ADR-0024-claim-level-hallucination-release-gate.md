# ADR-0024 — Claim-level hallucination release gate

## Decision

Treat hallucination protection as a deterministic claim-level release gate over the exact Self Corrective RAG evidence set. A proposed claim cannot be released as factual unless cited retrieval evidence supports it. Uncertain claims are qualified; unsupported or contradicted material claims are removed.

Evidence text that resembles instructions is classified as untrusted data and excluded from entailment scoring. The verifier does not execute instructions found in documents, logs, or retrieved context.

## Why

A second hidden retrieval or unconstrained model verifier would make the protection decision difficult to reproduce and could silently widen authorization. Reusing the stored Self Corrective RAG run preserves tenant scope, lineage, and auditability.
