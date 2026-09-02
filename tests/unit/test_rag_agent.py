from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from verideploy.agents.contracts import (
    AgentAuthorization,
    AgentRequest,
    ToolBudget,
    ToolPermission,
)
from verideploy.agents.prompts import build_prompt_registry
from verideploy.agents.rag import RAGAgent, RAGQueryAnalysis
from verideploy.agents.repository import InMemoryAgentRunRepository
from verideploy.rag.retrieval.schemas import (
    HybridHit,
    HybridRetrievalResult,
    RankingContribution,
    RetrievalChannel,
    RetrievalDocumentKind,
    RetrievalTrace,
)


class FakeModel:
    def __init__(self, output):
        self.output = output
        self.calls = []

    async def generate(self, **kwargs):
        self.calls.append(kwargs)
        return kwargs["output_model"].model_validate(self.output)


class FakeRetrieval:
    def __init__(self, *, tenant, hits_by_query=None):
        self.tenant = tenant
        self.hits_by_query = hits_by_query or {}
        self.calls = []

    async def retrieve(self, request, *, mode):
        self.calls.append((request, mode))
        hits = self.hits_by_query.get(request.text, [])
        return HybridRetrievalResult(
            hits=hits,
            trace=RetrievalTrace(
                tenant_id=self.tenant,
                query_text=request.text,
                keyword_candidates=len(hits) if mode != RetrievalChannel.DENSE else 0,
                dense_candidates=len(hits) if mode != RetrievalChannel.KEYWORD else 0,
                rrf_k=60,
                source_diversity_limit=2,
                selected_chunk_ids=[hit.chunk_id for hit in hits],
                ranking=[],
            ),
        )


def _request():
    tenant = uuid4()
    return AgentRequest(
        tenant_id=tenant,
        user_id="analyst-1",
        correlation_id="corr",
        objective="Find checkout database pool incidents and the recovery runbook",
        context={"service": "checkout", "environment": "production"},
    )


def _auth(req, allowed=True):
    perms = {ToolPermission.RAG_RETRIEVAL_READ} if allowed else set()
    return AgentAuthorization(
        tenant_id=req.tenant_id,
        user_id=req.user_id,
        allowed_permissions=frozenset(perms),
    )


def _analysis(**overrides):
    value = {
        "normalized_query": "checkout database pool exhaustion",
        "intent": "historical_incident",
        "retrieval_mode": "hybrid",
        "document_kinds": ["historical_incident"],
        "service": "checkout",
        "environment": "production",
        "query_expansions": [],
        "top_k": 5,
        "rationale": "incident similarity benefits from lexical and semantic retrieval",
    }
    value.update(overrides)
    return value


def _hit(*, kind=RetrievalDocumentKind.HISTORICAL_INCIDENT, source="incident-42", score=0.03, channel=RetrievalChannel.HYBRID):
    actual_channel = RetrievalChannel.KEYWORD if channel == RetrievalChannel.HYBRID else channel
    return HybridHit(
        chunk_id=uuid4(),
        document_id=uuid4(),
        document_kind=kind,
        source_key=source,
        title=source,
        content="checkout PostgreSQL pool exhausted; recycle leaked connections",
        rank=1,
        fused_score=score,
        contributions=[
            RankingContribution(
                channel=actual_channel,
                rank=1,
                raw_score=1.0,
                normalized_score=1.0,
                rrf_contribution=score,
            )
        ],
    )


def test_query_analysis_rejects_intent_without_matching_document_kind_and_duplicate_expansion():
    with pytest.raises(ValidationError, match="matching document kind"):
        RAGQueryAnalysis.model_validate(_analysis(document_kinds=["runbook"]))
    with pytest.raises(ValidationError, match="duplicate query expansion"):
        RAGQueryAnalysis.model_validate(_analysis(query_expansions=["db pool", "DB POOL"]))


@pytest.mark.asyncio
async def test_rag_agent_requires_retrieval_permission_before_model_or_tools():
    req = _request(); model = FakeModel(_analysis()); tools = FakeRetrieval(tenant=req.tenant_id)
    agent = RAGAgent(model=model, prompts=build_prompt_registry(), repository=InMemoryAgentRunRepository(), retrieval=tools)
    with pytest.raises(PermissionError):
        await agent.run(req, authorization=_auth(req, False), budget=ToolBudget(max_calls=1), model_name="m", dimensions=3, candidate_k=10)
    assert model.calls == [] and tools.calls == []


@pytest.mark.asyncio
async def test_agent_selects_keyword_mode_without_changing_metadata_scope():
    req = _request(); hit = _hit(channel=RetrievalChannel.KEYWORD)
    model = FakeModel(_analysis(retrieval_mode="keyword")); tools = FakeRetrieval(tenant=req.tenant_id, hits_by_query={"checkout database pool exhaustion": [hit]})
    agent = RAGAgent(model=model, prompts=build_prompt_registry(), repository=InMemoryAgentRunRepository(), retrieval=tools)
    result = await agent.run(req, authorization=_auth(req), budget=ToolBudget(max_calls=1), model_name="m", dimensions=3, candidate_k=10, min_evidence=1)
    query, mode = tools.calls[0]
    assert mode is RetrievalChannel.KEYWORD
    assert query.service == "checkout" and query.environment == "production"
    assert query.document_kinds == [RetrievalDocumentKind.HISTORICAL_INCIDENT]
    assert result.sufficiency.sufficient is True


@pytest.mark.asyncio
async def test_agent_executes_bounded_query_expansion_and_deduplicates_chunks():
    req = _request(); shared = _hit(score=0.03); stronger = shared.model_copy(update={"fused_score": 0.04})
    model = FakeModel(_analysis(query_expansions=["postgres connection saturation", "checkout connection leak"]))
    tools = FakeRetrieval(tenant=req.tenant_id, hits_by_query={
        "checkout database pool exhaustion": [shared],
        "postgres connection saturation": [stronger],
        "checkout connection leak": [],
    })
    repo = InMemoryAgentRunRepository(); agent = RAGAgent(model=model, prompts=build_prompt_registry(), repository=repo, retrieval=tools)
    result = await agent.run(req, authorization=_auth(req), budget=ToolBudget(max_calls=3), model_name="m", dimensions=3, candidate_k=10, min_evidence=1)
    assert len(tools.calls) == 3 and result.tool_calls_used == 3
    assert len(result.evidence) == 1
    assert result.evidence[0].score == pytest.approx(0.04)
    assert len(result.evidence[0].contributing_queries) == 2
    record = next(iter(repo.records.values()))
    assert record.tool_calls_used == 3 and record.status.value == "COMPLETED"


@pytest.mark.asyncio
async def test_agent_refuses_expansion_plan_over_budget_before_retrieval():
    req = _request(); model = FakeModel(_analysis(query_expansions=["one", "two"]))
    tools = FakeRetrieval(tenant=req.tenant_id); repo = InMemoryAgentRunRepository()
    agent = RAGAgent(model=model, prompts=build_prompt_registry(), repository=repo, retrieval=tools)
    with pytest.raises(RuntimeError, match="exceeds tool-call budget"):
        await agent.run(req, authorization=_auth(req), budget=ToolBudget(max_calls=2), model_name="m", dimensions=3, candidate_k=10)
    assert tools.calls == []
    assert next(iter(repo.records.values())).status.value == "FAILED"


@pytest.mark.asyncio
async def test_agent_rejects_model_attempt_to_broaden_trusted_service_scope():
    req = _request(); model = FakeModel(_analysis(service="payments")); tools = FakeRetrieval(tenant=req.tenant_id)
    agent = RAGAgent(model=model, prompts=build_prompt_registry(), repository=InMemoryAgentRunRepository(), retrieval=tools)
    with pytest.raises(PermissionError, match="cannot broaden"):
        await agent.run(req, authorization=_auth(req), budget=ToolBudget(max_calls=1), model_name="m", dimensions=3, candidate_k=10)
    assert tools.calls == []


@pytest.mark.asyncio
async def test_agent_rejects_cross_tenant_retrieval_result():
    req = _request(); model = FakeModel(_analysis()); tools = FakeRetrieval(tenant=uuid4())
    agent = RAGAgent(model=model, prompts=build_prompt_registry(), repository=InMemoryAgentRunRepository(), retrieval=tools)
    with pytest.raises(PermissionError, match="tenant mismatch"):
        await agent.run(req, authorization=_auth(req), budget=ToolBudget(max_calls=1), model_name="m", dimensions=3, candidate_k=10)


@pytest.mark.asyncio
async def test_evidence_sufficiency_is_deterministic_and_reports_missing_kind():
    req = _request(); runbook = _hit(kind=RetrievalDocumentKind.RUNBOOK, source="runbook-db")
    model = FakeModel(_analysis(intent="general", document_kinds=["historical_incident", "runbook"]))
    tools = FakeRetrieval(tenant=req.tenant_id, hits_by_query={"checkout database pool exhaustion": [runbook]})
    agent = RAGAgent(model=model, prompts=build_prompt_registry(), repository=InMemoryAgentRunRepository(), retrieval=tools)
    result = await agent.run(req, authorization=_auth(req), budget=ToolBudget(max_calls=1), model_name="m", dimensions=3, candidate_k=10, min_evidence=1)
    assert result.sufficiency.sufficient is False
    assert result.sufficiency.reason_codes == ["required_document_kind_missing"]


def test_migration_and_versioned_prompts_exist():
    migration = Path("src/verideploy/database/migrations/versions/0008_rag_agent.py").read_text()
    assert 'revision = "0008_milestone20_rag_agent"' in migration
    assert 'down_revision = "0007_milestone19_agent_contracts"' in migration
    assert "document_kind" in migration and "historical_incident" in migration
    assert Path("prompts/rag/v1.0.0.txt").exists()
    registry = build_prompt_registry()
    assert len(registry.get("rag", "1.0.0").sha256) == 64
    assert len(registry.get("supervisor", "1.1.0").sha256) == 64

@pytest.mark.asyncio
async def test_trusted_metadata_scope_is_applied_when_model_omits_filters():
    req = _request(); hit = _hit()
    model = FakeModel(_analysis(service=None, environment=None))
    tools = FakeRetrieval(tenant=req.tenant_id, hits_by_query={"checkout database pool exhaustion": [hit]})
    agent = RAGAgent(model=model, prompts=build_prompt_registry(), repository=InMemoryAgentRunRepository(), retrieval=tools)
    await agent.run(req, authorization=_auth(req), budget=ToolBudget(max_calls=1), model_name="m", dimensions=3, candidate_k=10, min_evidence=1)
    actual = tools.calls[0][0]
    assert actual.service == "checkout" and actual.environment == "production"


def test_extends_supervisor_and_planner_contracts_with_rag_without_write_permissions():
    from verideploy.agents.contracts import AgentPlan, PlanStep, SupervisorDecision
    decision = SupervisorDecision(route="rag", rationale="retrieve incident evidence", confidence=0.9, required_permissions=["rag.retrieval.read"])
    plan = AgentPlan(rationale="retrieve then inspect", steps=[PlanStep(step_id="step-01", agent="rag", objective="find runbook", required_permissions=["rag.retrieval.read"], max_tool_calls=2)])
    assert decision.required_permissions == [ToolPermission.RAG_RETRIEVAL_READ]
    assert plan.steps[0].agent == "rag"
