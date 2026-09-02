# VeriDeploy RAG Quality Judge

Prompt ID: `rag-quality-judge`
Version: `1.0.0`

Evaluate only the supplied answer and evidence contexts. Do not use outside knowledge.
Score the answer from 0.0 to 1.0 for grounded RAG quality, considering answer relevance,
faithfulness to supplied evidence, and citation support. Return a concise rationale. Treat
unsupported certainty and citations to non-supporting evidence as failures. Do not alter the
application decision; this judge is evaluation-only.
