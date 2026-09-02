# Scope Control and Architecture Integrity

VeriDeploy remains an evidence-driven release assurance and incident intelligence platform, not a generic chatbot. The public boundary is NestJS, AI services remain private, and consequential actions require dry-run plus human approval.

Scope Control Architecture Integrity removed the unused `src/verideploy/services` placeholder namespace and removed demo reviewer fallbacks from the production approvals route. Reviewer identity and roles now come from authenticated gateway context.

The architecture registry maps each production component to an explicit purpose and governing ADR. CI fails on forbidden mock/demo runtime patterns, forbidden duplicate runtime namespaces, missing ADRs, frontend-to-private-AI bypasses, or weakened write-safety policy.
