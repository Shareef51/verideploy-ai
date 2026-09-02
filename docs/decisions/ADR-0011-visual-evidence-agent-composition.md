# ADR-0011 — Compose visual retrieval and image intelligence behind one agent

## Decision

`VisualEvidenceAgent` composes Visual Document Retrieval visual retrieval with Image Intelligence Layer secure image intelligence. It does not directly call remote image URLs, create a second visual index, or treat retrieval score as observed evidence.

## Rationale

Retrieval and visual interpretation answer different questions. Retrieval identifies candidate pages; image intelligence produces direct observations and qualified inferences. Keeping those boundaries separate provides provenance, tenant isolation, reusable tests, and explicit uncertainty handling.

## Security

Only indexed image paths are accepted by the production adapter. The exact indexed SHA-256 must match before analysis. Trusted document scope cannot be broadened by model output. Embedded text remains untrusted evidence under the Image Intelligence Layer prompt-injection boundary.
