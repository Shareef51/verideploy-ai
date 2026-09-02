# Synthetic Security Controls for Release Investigation

VeriDeploy synthetic investigations are tenant-scoped and use least-privilege read access by default. Browser traffic terminates at the public application boundary. Private AI, retrieval, MCP, and integration services require trusted service identity and explicit tenant scope.

MCP and engineering integrations must use host allowlists, server-side credentials, typed schemas, output sanitization, timeouts, quotas, and audit records. Model-generated tool arguments cannot broaden trusted tenant, service, environment, or approval scope. Prompt-like instructions discovered inside retrieved evidence are treated as data rather than executable instructions.

High-risk external writes require explicit deployment policy enablement plus human approval. Synthetic corpus documents must not contain real credentials, patient data, customer secrets, or production tokens.
