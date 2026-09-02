from __future__ import annotations
from datetime import datetime, timezone
from itertools import chain, combinations
from pathlib import Path
from uuid import uuid4
import pytest

from verideploy.rag.access.cache import ScopedRetrievalCache
from verideploy.rag.access.schemas import (
    RequestedMetadataFilters, RetrievalAuthorizationScope, build_effective_scope,
    READ_PERMISSION, VISUAL_PERMISSION, PREVIEW_PERMISSION,
)

def subsets(items):
    xs=list(items)
    return [frozenset(c) for r in range(len(xs)+1) for c in combinations(xs,r)]

def test_property_effective_scope_never_widens_trusted_sets():
    tenant=uuid4(); universe=["checkout","payments","ledger"]
    for trusted in subsets(universe):
        for requested in subsets(universe):
            auth=RetrievalAuthorizationScope(tenant_id=tenant,permissions=frozenset({READ_PERMISSION}),allowed_services=trusted)
            eff=build_effective_scope(authorization=auth,requested=RequestedMetadataFilters(services=list(requested)))
            assert eff.services is not None
            assert set(eff.services).issubset(set(trusted))
            if requested and not (set(trusted)&set(requested)):
                assert eff.empty

def test_property_multiple_dimensions_never_widen():
    tenant=uuid4()
    trusted=RetrievalAuthorizationScope(tenant_id=tenant,permissions=frozenset({READ_PERMISSION}),allowed_services=frozenset({"checkout","ledger"}),allowed_environments=frozenset({"production"}),allowed_teams=frozenset({"commerce","platform"}),allowed_document_kinds=frozenset({"runbook","architecture"}))
    cases=[
        RequestedMetadataFilters(),
        RequestedMetadataFilters(services=["checkout"]),
        RequestedMetadataFilters(environments=["staging"]),
        RequestedMetadataFilters(teams=["commerce"],document_kinds=["runbook"]),
        RequestedMetadataFilters(services=["checkout"],environments=["production"],teams=["commerce"],document_kinds=["architecture"]),
    ]
    for req in cases:
        eff=build_effective_scope(authorization=trusted,requested=req)
        if eff.services is not None: assert set(eff.services)<=set(trusted.allowed_services)
        if eff.environments is not None: assert set(eff.environments)<=set(trusted.allowed_environments)
        if eff.teams is not None: assert set(eff.teams)<=set(trusted.allowed_teams)
        if eff.document_kinds is not None: assert set(eff.document_kinds)<=set(trusted.allowed_document_kinds)

def test_dates_severity_and_permission_are_fail_closed():
    tenant=uuid4(); start=datetime(2026,1,1,tzinfo=timezone.utc); end=datetime(2026,1,2,tzinfo=timezone.utc)
    auth=RetrievalAuthorizationScope(tenant_id=tenant,permissions=frozenset())
    eff=build_effective_scope(authorization=auth,requested=RequestedMetadataFilters(severities=["sev1"],occurred_from=start,occurred_to=end))
    assert eff.empty and eff.severities==frozenset({"sev1"}) and eff.occurred_from==start and eff.occurred_to==end

def test_cache_is_partitioned_by_effective_authorization_scope():
    tenant=uuid4(); cache=ScopedRetrievalCache[dict]()
    broad=build_effective_scope(authorization=RetrievalAuthorizationScope(tenant_id=tenant,permissions=frozenset({READ_PERMISSION}),allowed_services=frozenset({"checkout","ledger"})))
    narrow=build_effective_scope(authorization=RetrievalAuthorizationScope(tenant_id=tenant,permissions=frozenset({READ_PERMISSION}),allowed_services=frozenset({"checkout"})))
    cache.put("same-query",broad,{"documents":["checkout","ledger"]})
    assert cache.get("same-query",narrow) is None
    assert cache.get("same-query",broad)=={"documents":["checkout","ledger"]}

def test_keyword_vector_visual_and_preview_sql_apply_all_security_dimensions():
    retrieval=Path("src/verideploy/rag/retrieval/repository.py").read_text()
    visual=Path("src/verideploy/rag/visual_retrieval/repository.py").read_text()
    preview=Path("src/verideploy/rag/access/source_preview.py").read_text()
    for text in (retrieval,visual,preview):
        assert "required_permission" in text
        assert "occurred_at" in text
        assert "severity" in text
        assert "team" in text
        assert "service" in text
        assert "environment" in text
    assert retrieval.count("effective_scope") >= 10
    assert "visual_documents d" in visual
    assert "d.required_permission=ANY" in preview

def test_visual_and_preview_permission_names_are_distinct():
    assert READ_PERMISSION != VISUAL_PERMISSION != PREVIEW_PERMISSION

def test_migration_adds_metadata_indexes_and_is_reversible():
    text=Path("src/verideploy/database/migrations/versions/0017_metadata_filtering_authorization.py").read_text()
    assert 'down_revision="0016_milestone34_retrieval_pipeline_orchestration"' in text
    for token in ("severity","team","occurred_at","required_permission","ix_retrieval_metadata","ix_visual_metadata"):
        assert token in text
    assert "drop_column" in text and "drop_index" in text

def test_orchestration_propagates_metadata_filters_and_authorization():
    text=Path("src/verideploy/rag/orchestration/service.py").read_text()
    assert "metadata_filters=request.metadata_filters" in text
    assert "authorization=authorization" in text

def test_private_routes_accept_trusted_scope_headers_and_source_preview():
    text=Path("services/ai/routes/retrieval.py").read_text()
    for header in ("x_retrieval_permissions","x_allowed_services","x_allowed_environments","x_allowed_teams","x_allowed_document_kinds"):
        assert header in text
    assert '/source-preview/{document_id}' in text

def test_naive_metadata_dates_are_rejected():
    with pytest.raises(ValueError,match="timezone-aware"):
        RequestedMetadataFilters(occurred_from=datetime(2026,1,1))


@pytest.mark.asyncio
async def test_legacy_and_structured_filters_conflict_to_empty_scope():
    from dataclasses import dataclass
    from uuid import uuid4
    from verideploy.rag.retrieval.service import HybridRetriever
    from verideploy.rag.retrieval.schemas import RetrievalQuery, RetrievalDocumentKind
    class Repo:
        supports_scope=True
        def keyword_search(self,**kwargs):
            assert kwargs["effective_scope"].empty
            return []
        def dense_search(self,**kwargs): return []
        def get_embedding_model_id(self,**kwargs): raise AssertionError("dense path not used")
    class Emb: pass
    tenant=uuid4(); r=HybridRetriever(Repo(),Emb())
    q=RetrievalQuery(tenant_id=tenant,text="x",top_k=1,candidate_k=1,model_name="m",dimensions=3,service="checkout",metadata_filters=RequestedMetadataFilters(services=["ledger"]))
    result=await r.retrieve_mode(q,mode=__import__("verideploy.rag.retrieval.schemas",fromlist=["RetrievalChannel"]).RetrievalChannel.KEYWORD)
    assert result.hits==[] and result.trace.effective_filters["empty"] is True
