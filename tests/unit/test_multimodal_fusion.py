from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from services.ai.fusion import get_multimodal_fusion_service
from services.ai.main import app
from verideploy.rag.fusion.schemas import (
    CitedMultimodalAnswer,
    CitedStatement,
    EvidenceChannel,
    FusionBudgets,
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
from verideploy.rag.visual_retrieval.schemas import (
    VisualBackend,
    VisualSearchHit,
    VisualSearchResult,
)


def _text_result(tenant_id, content: str = "checkout latency increased after connection pool exhaustion"):
    document_id = uuid4()
    chunk_id = uuid4()
    return HybridRetrievalResult(
        hits=[
            HybridHit(
                chunk_id=chunk_id,
                document_id=document_id,
                source_key="runbook/checkout.md",
                title="Checkout runbook",
                content=content,
                rank=1,
                fused_score=0.05,
                contributions=[
                    RankingContribution(
                        channel=RetrievalChannel.KEYWORD,
                        rank=1,
                        raw_score=0.8,
                        normalized_score=1.0,
                        rrf_contribution=0.02,
                    )
                ],
            )
        ],
        trace=RetrievalTrace(
            tenant_id=tenant_id,
            query_text="why checkout slow",
            keyword_candidates=1,
            dense_candidates=1,
            rrf_k=60,
            source_diversity_limit=2,
            selected_chunk_ids=[chunk_id],
            ranking=[],
        ),
    )


def _visual_result():
    return VisualSearchResult(
        backend=VisualBackend.CPU_FALLBACK,
        model_name="cpu-visual-fallback-v1",
        hits=[
            VisualSearchHit(
                page_id=uuid4(),
                document_id=uuid4(),
                page_number=2,
                score=0.91,
                backend=VisualBackend.CPU_FALLBACK,
                model_name="cpu-visual-fallback-v1",
                image_path="data/processed/visual_pages/tenant/doc/page-2.png",
                image_sha256="a" * 64,
            )
        ],
    )


def _runtime(tenant_id, content="p95 checkout latency rose from baseline after deploy"):
    return RuntimeEvidenceInput(
        tenant_id=tenant_id,
        kind=RuntimeEvidenceKind.METRIC,
        source_system="prometheus",
        source_id="checkout:p95:2026-08-17T07:00Z",
        title="Checkout P95 latency",
        content=content,
        relevance_score=0.95,
        source_confidence=0.99,
        observed_at=datetime.now(timezone.utc),
        service="checkout-service",
        environment="production",
    )


def test_normalizes_all_three_channels_with_citations():
    tenant_id = uuid4()
    result = MultimodalEvidenceFusion().fuse(
        MultimodalFusionRequest(
            tenant_id=tenant_id,
            query="why did checkout latency increase",
            text_result=_text_result(tenant_id),
            visual_result=_visual_result(), visual_tenant_id=tenant_id,
            runtime_evidence=[_runtime(tenant_id)],
        )
    )
    assert result.contributing_channels == [EvidenceChannel.TEXT, EvidenceChannel.VISUAL, EvidenceChannel.RUNTIME]
    assert len(result.evidence) == 3
    assert len(result.citations) == 3
    assert len({c.citation_id for c in result.citations}) == 3
    assert {c.channel for c in result.citations} == set(result.contributing_channels)


def test_visual_context_uses_reference_not_image_bytes():
    tenant_id = uuid4()
    result = MultimodalEvidenceFusion().fuse(
        MultimodalFusionRequest(tenant_id=tenant_id, query="chart", visual_result=_visual_result(), visual_tenant_id=tenant_id)
    )
    assert result.context[0].image_ref.endswith("page-2.png")
    assert "base64" not in result.context[0].content.lower()
    assert result.trace.images_used == 1


def test_duplicate_content_is_not_duplicated_in_context():
    tenant_id = uuid4()
    duplicate = "same evidence statement"
    result = MultimodalEvidenceFusion().fuse(
        MultimodalFusionRequest(
            tenant_id=tenant_id,
            query="duplicate",
            text_result=_text_result(tenant_id, duplicate),
            runtime_evidence=[_runtime(tenant_id, duplicate)],
        )
    )
    assert len(result.evidence) == 1
    assert result.trace.duplicate_count == 1
    assert len(result.citations) == 1


def test_token_and_image_budgets_are_enforced():
    tenant_id = uuid4()
    visual = _visual_result()
    visual.hits.append(
        VisualSearchHit(
            page_id=uuid4(), document_id=uuid4(), page_number=3, score=0.8,
            backend=VisualBackend.CPU_FALLBACK, model_name="cpu-visual-fallback-v1",
            image_path="data/processed/visual_pages/page-3.png", image_sha256="b" * 64,
        )
    )
    result = MultimodalEvidenceFusion().fuse(
        MultimodalFusionRequest(
            tenant_id=tenant_id,
            query="budget",
            text_result=_text_result(tenant_id, "x" * 2_000),
            visual_result=visual, visual_tenant_id=tenant_id,
            runtime_evidence=[_runtime(tenant_id, "short runtime signal")],
            budgets=FusionBudgets(max_context_tokens=256, max_images=1, max_total_evidence=10, max_per_channel=5),
        )
    )
    assert result.trace.tokens_used <= 256
    assert result.trace.images_used <= 1
    assert result.trace.dropped_for_token_budget >= 1
    assert result.trace.dropped_for_image_budget >= 1


def test_round_robin_preserves_cross_channel_coverage():
    tenant_id = uuid4()
    text = _text_result(tenant_id)
    # Add multiple high-scoring text hits that must not crowd out runtime/visual.
    for _ in range(4):
        original = text.hits[0]
        text.hits.append(
            original.model_copy(update={"chunk_id": uuid4(), "rank": len(text.hits) + 1, "fused_score": 0.1})
        )
    result = MultimodalEvidenceFusion().fuse(
        MultimodalFusionRequest(
            tenant_id=tenant_id,
            query="coverage",
            text_result=text,
            visual_result=_visual_result(), visual_tenant_id=tenant_id,
            runtime_evidence=[_runtime(tenant_id)],
            budgets=FusionBudgets(max_context_tokens=1000, max_images=1, max_total_evidence=3, max_per_channel=3),
        )
    )
    assert set(result.contributing_channels) == {EvidenceChannel.TEXT, EvidenceChannel.VISUAL, EvidenceChannel.RUNTIME}
    assert len(result.evidence) == 3


def test_cited_answer_must_cover_every_contributing_channel():
    tenant_id = uuid4()
    fusion = MultimodalEvidenceFusion()
    result = fusion.fuse(
        MultimodalFusionRequest(
            tenant_id=tenant_id,
            query="grounded answer",
            text_result=_text_result(tenant_id),
            visual_result=_visual_result(), visual_tenant_id=tenant_id,
            runtime_evidence=[_runtime(tenant_id)],
        )
    )
    first = result.citations[0]
    incomplete = CitedMultimodalAnswer(
        summary="incomplete",
        statements=[CitedStatement(text="claim", citation_ids=[first.citation_id])],
    )
    with pytest.raises(ValueError, match="every contributing channel"):
        fusion.validate_cited_answer(result, incomplete)

    complete = CitedMultimodalAnswer(
        summary="grounded",
        statements=[
            CitedStatement(text=f"claim from {citation.channel}", citation_ids=[citation.citation_id])
            for citation in result.citations
        ],
    )
    assert fusion.validate_cited_answer(result, complete) is complete


def test_cited_answer_rejects_unknown_citation():
    tenant_id = uuid4()
    fusion = MultimodalEvidenceFusion()
    result = fusion.fuse(MultimodalFusionRequest(tenant_id=tenant_id, query="x", runtime_evidence=[_runtime(tenant_id)]))
    answer = CitedMultimodalAnswer(
        summary="bad",
        statements=[CitedStatement(text="claim", citation_ids=["VD-EVID-000000000000"])],
    )
    with pytest.raises(ValueError, match="unknown citation"):
        fusion.validate_cited_answer(result, answer)


def test_fusion_request_rejects_cross_tenant_runtime_evidence():
    with pytest.raises(ValueError, match="runtime evidence tenant"):
        MultimodalFusionRequest(
            tenant_id=uuid4(), query="tenant", runtime_evidence=[_runtime(uuid4())]
        )


def test_private_fusion_api_requires_trusted_identity_and_tenant_scope():
    tenant_id = uuid4()
    client = TestClient(app)
    payload = MultimodalFusionRequest(
        tenant_id=tenant_id, query="runtime", runtime_evidence=[_runtime(tenant_id)]
    ).model_dump(mode="json")

    response = client.post("/internal/v1/rag/fuse", json=payload)
    assert response.status_code == 401

    response = client.post(
        "/internal/v1/rag/fuse",
        json=payload,
        headers={"x-internal-service": "verideploy-investigation-worker", "x-tenant-id": str(uuid4())},
    )
    assert response.status_code == 403

    response = client.post(
        "/internal/v1/rag/fuse",
        json=payload,
        headers={"x-internal-service": "verideploy-investigation-worker", "x-tenant-id": str(tenant_id)},
    )
    assert response.status_code == 200
    assert response.json()["contributing_channels"] == ["runtime"]


def test_visual_result_requires_matching_tenant_scope():
    tenant_id = uuid4()
    with pytest.raises(ValueError, match="visual_tenant_id is required"):
        MultimodalFusionRequest(tenant_id=tenant_id, query="visual", visual_result=_visual_result())
    with pytest.raises(ValueError, match="visual retrieval tenant"):
        MultimodalFusionRequest(
            tenant_id=tenant_id, query="visual", visual_result=_visual_result(), visual_tenant_id=uuid4()
        )
