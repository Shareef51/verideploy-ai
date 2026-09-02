from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from verideploy.rag.fusion.schemas import (
    CitedMultimodalAnswer,
    CitedStatement,
    EvidenceChannel,
    MultimodalFusionRequest,
    RuntimeEvidenceInput,
    RuntimeEvidenceKind,
)
from verideploy.rag.fusion.service import MultimodalEvidenceFusion
from verideploy.rag.retrieval.schemas import (
    HybridHit,
    HybridRetrievalResult,
    RankingContribution,
    RetrievalChannel,
    RetrievalTrace,
)
from verideploy.rag.visual_retrieval.schemas import VisualBackend, VisualSearchHit, VisualSearchResult


def build_case():
    tenant_id = uuid4()
    chunk_id = uuid4()
    text = HybridRetrievalResult(
        hits=[HybridHit(
            chunk_id=chunk_id, document_id=uuid4(), source_key="runbooks/checkout.md",
            title="Checkout database runbook", content="Connection pool exhaustion can cause checkout latency after a deployment.",
            rank=1, fused_score=0.04,
            contributions=[RankingContribution(channel=RetrievalChannel.KEYWORD, rank=1, raw_score=1.0, normalized_score=1.0, rrf_contribution=0.02)],
        )],
        trace=RetrievalTrace(tenant_id=tenant_id, query_text="checkout latency", keyword_candidates=1, dense_candidates=1,
                             rrf_k=60, source_diversity_limit=2, selected_chunk_ids=[chunk_id], ranking=[]),
    )
    visual = VisualSearchResult(
        backend=VisualBackend.CPU_FALLBACK, model_name="cpu-visual-fallback-v1",
        hits=[VisualSearchHit(page_id=uuid4(), document_id=uuid4(), page_number=2, score=0.93,
                              backend=VisualBackend.CPU_FALLBACK, model_name="cpu-visual-fallback-v1",
                              image_path="data/processed/visual_pages/dashboard.png", image_sha256="c" * 64)],
    )
    runtime = RuntimeEvidenceInput(
        tenant_id=tenant_id, kind=RuntimeEvidenceKind.METRIC, source_system="prometheus",
        source_id="checkout-latency-p95", title="Checkout latency P95",
        content="Checkout P95 latency rose immediately after the release timestamp.", relevance_score=0.98,
        source_confidence=0.99, observed_at=datetime.now(timezone.utc), service="checkout-service", environment="production",
    )
    return tenant_id, text, visual, runtime


def main() -> int:
    tenant_id, text, visual, runtime = build_case()
    fusion = MultimodalEvidenceFusion()
    result = fusion.fuse(MultimodalFusionRequest(
        tenant_id=tenant_id, query="why did checkout latency increase after the release",
        text_result=text, visual_result=visual, visual_tenant_id=tenant_id, runtime_evidence=[runtime],
    ))
    answer = CitedMultimodalAnswer(
        summary="Evidence-backed checkout latency investigation context.",
        statements=[CitedStatement(text=f"Grounded {c.channel.value} statement", citation_ids=[c.citation_id]) for c in result.citations],
    )
    fusion.validate_cited_answer(result, answer)

    channels = set(result.contributing_channels)
    expected = {EvidenceChannel.TEXT, EvidenceChannel.VISUAL, EvidenceChannel.RUNTIME}
    citation_coverage = len({c.channel for c in result.citations} & expected) / len(expected)
    duplication_rate = 1.0 - (len({e.evidence_id for e in result.evidence}) / max(1, len(result.evidence)))
    report = {
        "citation_channel_coverage": citation_coverage,
        "duplicate_evidence_rate": duplication_rate,
        "contributing_channels": [c.value for c in result.contributing_channels],
        "tokens_used": result.trace.tokens_used,
        "images_used": result.trace.images_used,
        "gate": citation_coverage == 1.0 and duplication_rate == 0.0 and channels == expected,
    }
    Path("artifacts/benchmark.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["gate"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
