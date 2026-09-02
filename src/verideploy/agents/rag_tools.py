from __future__ import annotations

from verideploy.rag.retrieval.schemas import HybridRetrievalResult, RetrievalChannel, RetrievalQuery
from verideploy.rag.retrieval.service import HybridRetriever
from verideploy.rag.access.schemas import READ_PERMISSION, RetrievalAuthorizationScope
from verideploy.rag.self_corrective.schemas import ExternalSearchMode, SelfCorrectiveRAGRequest
from verideploy.rag.self_corrective.service import SelfCorrectiveRAG
from verideploy.rag.orchestration.schemas import RetrievalPipelineRequest
from verideploy.rag.retrieval.schemas import HybridHit, RankingContribution, RetrievalTrace


class HybridRetrieverRAGTool:
    """Agent-facing adapter over the hybrid retriever.

    The RAGAgent may select one of the already-authorized retrieval modes, but cannot
    bypass the repository/embedding/tenant controls.
    """

    def __init__(self, retriever: HybridRetriever) -> None:
        self.retriever = retriever

    async def retrieve(
        self, request: RetrievalQuery, *, mode: RetrievalChannel
    ) -> HybridRetrievalResult:
        return await self.retriever.retrieve_mode(request, mode=mode)


class ProductionRAGTool:
    """Single production adapter: orchestration pipeline plus corrective retrieval.

    The wrapped pipeline performs query analysis/decomposition, hybrid retrieval,
    fusion, reranking, parent resolution and context building. SelfCorrectiveRAG grades
    that evidence and retries within policy before this adapter returns agent evidence.
    """

    def __init__(self, controller: SelfCorrectiveRAG, *, max_attempts: int=3, max_query_rewrites: int=2, allow_scope_relaxation: bool=True, external_search_mode: ExternalSearchMode=ExternalSearchMode.DISABLED) -> None:
        self.controller=controller; self.max_attempts=max_attempts; self.max_query_rewrites=max_query_rewrites; self.allow_scope_relaxation=allow_scope_relaxation; self.external_search_mode=external_search_mode

    async def retrieve(self, request: RetrievalQuery, *, mode: RetrievalChannel) -> HybridRetrievalResult:
        authorization=RetrievalAuthorizationScope(tenant_id=request.tenant_id,permissions=frozenset({READ_PERMISSION}))
        result=await self.controller.run(SelfCorrectiveRAGRequest(retrieval=RetrievalPipelineRequest(tenant_id=request.tenant_id,query=request.text,service=request.service,environment=request.environment,document_kinds=request.document_kinds,metadata_filters=request.metadata_filters,retrieval_mode=mode,top_k=request.top_k,candidate_k=request.candidate_k,model_name=request.model_name,dimensions=request.dimensions,query_purpose="incident_rca"),max_attempts=self.max_attempts,max_query_rewrites=self.max_query_rewrites,allow_requested_scope_relaxation=self.allow_scope_relaxation,external_search_mode=self.external_search_mode),authorization=authorization)
        contexts={item.chunk_id:item for item in result.final_retrieval.context}
        hits=[]
        for candidate in result.final_retrieval.candidates:
            contribution_channel=candidate.channels[0] if candidate.channels else mode
            score=max(candidate.retrieval_score,1e-12)
            hits.append(HybridHit(chunk_id=candidate.chunk_id,document_id=candidate.document_id,source_key=candidate.source_key,title=candidate.title,content=contexts.get(candidate.chunk_id).content if candidate.chunk_id in contexts else candidate.content,rank=candidate.final_rank,fused_score=score,contributions=[RankingContribution(channel=contribution_channel,rank=candidate.final_rank,raw_score=score,normalized_score=candidate.rerank_score,rrf_contribution=max(score,1e-12))],document_kind=candidate.document_kind))
        trace=RetrievalTrace(trace_id=result.run_id,tenant_id=request.tenant_id,query_text=request.text,keyword_candidates=len(hits),dense_candidates=len(hits),rrf_k=60,source_diversity_limit=2,selected_chunk_ids=[x.chunk_id for x in hits],ranking=[{"chunk_id":str(x.chunk_id),"rank":x.rank,"self_corrective_run_id":str(result.run_id),"answerable":result.answerable,"stop_reason":result.stop_reason.value} for x in hits])
        return HybridRetrievalResult(hits=hits,trace=trace)
