from __future__ import annotations
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol
import asyncio

class MigrationPhase(StrEnum):
    DUAL_WRITE="dual_write"; REEMBEDDING="reembedding"; SHADOW="shadow"; READY="ready"; ACTIVE="active"; RETIRED="retired"

@dataclass(frozen=True)
class RetrievalQuality:
    recall: float; mrr: float; ndcg: float; sample_size: int

@dataclass(frozen=True)
class EmbeddingIndexVersion:
    name: str; model: str; dimensions: int; phase: MigrationPhase

class EmbeddingMigrationStore(Protocol):
    def save_index(self,index:EmbeddingIndexVersion)->None: ...
    def record_shadow(self,source:str,target:str,baseline:RetrievalQuality,candidate:RetrievalQuality)->None: ...
    def activate(self,target:str,source:str)->None: ...

class EmbeddingUpgradeController:
    """Explicit dual-write → backfill → shadow-eval → cutover state machine."""
    def __init__(self,store:EmbeddingMigrationStore,*,minimum_recall_ratio:float=.98,minimum_ndcg_ratio:float=.98): self.store=store;self.minimum_recall_ratio=minimum_recall_ratio;self.minimum_ndcg_ratio=minimum_ndcg_ratio
    def begin(self,source:EmbeddingIndexVersion,target:EmbeddingIndexVersion)->EmbeddingIndexVersion:
        if source.phase is not MigrationPhase.ACTIVE or target.name==source.name: raise ValueError("migration requires distinct source and target indexes")
        staged=EmbeddingIndexVersion(target.name,target.model,target.dimensions,MigrationPhase.DUAL_WRITE);self.store.save_index(staged);return staged
    def mark_backfill_complete(self,target:EmbeddingIndexVersion)->EmbeddingIndexVersion:
        if target.phase not in {MigrationPhase.DUAL_WRITE,MigrationPhase.REEMBEDDING}: raise ValueError("target is not being populated")
        shadow=EmbeddingIndexVersion(target.name,target.model,target.dimensions,MigrationPhase.SHADOW);self.store.save_index(shadow);return shadow
    def evaluate_and_switch(self,source:EmbeddingIndexVersion,target:EmbeddingIndexVersion,baseline:RetrievalQuality,candidate:RetrievalQuality)->EmbeddingIndexVersion:
        if target.phase is not MigrationPhase.SHADOW or candidate.sample_size<1: raise ValueError("shadow evaluation is required before cutover")
        self.store.record_shadow(source.name,target.name,baseline,candidate)
        if candidate.recall < baseline.recall*self.minimum_recall_ratio or candidate.ndcg < baseline.ndcg*self.minimum_ndcg_ratio or candidate.mrr < baseline.mrr*self.minimum_ndcg_ratio: raise RuntimeError("candidate embedding index failed retrieval quality gate")
        self.store.activate(target.name,source.name);return EmbeddingIndexVersion(target.name,target.model,target.dimensions,MigrationPhase.ACTIVE)


class DualWriteEmbeddingPipeline:
    """Writes new/updated chunks to both indexes while migration is active."""
    def __init__(self, primary, candidate, *, candidate_model: str, candidate_dimensions: int):
        self.primary=primary;self.candidate=candidate;self.candidate_model=candidate_model;self.candidate_dimensions=candidate_dimensions
    async def embed(self, request):
        candidate_request=request.model_copy(update={"model":self.candidate_model,"dimensions":self.candidate_dimensions})
        primary, _candidate = await asyncio.gather(self.primary.embed(request),self.candidate.embed(candidate_request))
        return primary
