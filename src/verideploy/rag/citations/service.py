from __future__ import annotations

import hashlib
import json
from uuid import UUID, UUID as UUIDType, uuid5

from verideploy.rag.access.schemas import PREVIEW_PERMISSION, RequestedMetadataFilters, RetrievalAuthorizationScope, build_effective_scope
from verideploy.rag.hallucination.repository import HallucinationProtectionRepository
from verideploy.rag.hallucination.schemas import ClaimReleaseAction, ClaimSupportLabel
from verideploy.rag.self_corrective.repository import SelfCorrectiveRunRepository
from .repository import CitationRepository, CitationSourceRepository
from .schemas import CitationBuildRequest, CitationBundle, CitationPreview, CitationRecord, ClaimCitationLink, TextLocator

CITATION_NAMESPACE=UUIDType("67b5f68b-1f22-5fa8-8ec0-f54860910f38")
CITATION_VERSION="1.0.0"


def stable_citation_id(*, tenant_id:UUID,document_id:UUID,chunk_id:UUID,source_version:str,evidence_sha256:str,locator)->UUID:
    loc=json.dumps(locator.model_dump(mode="json"),sort_keys=True,separators=(",",":"))
    key=f"{tenant_id}|{document_id}|{chunk_id}|{source_version}|{evidence_sha256}|{loc}"
    return uuid5(CITATION_NAMESPACE,key)


class CitationService:
    def __init__(self, *, hallucination_runs: HallucinationProtectionRepository, source_runs: SelfCorrectiveRunRepository,
                 repository: CitationRepository, sources: CitationSourceRepository, supported_threshold: float = 0.68,
                 uncertain_threshold: float = 0.42) -> None:
        self.hallucination_runs=hallucination_runs; self.source_runs=source_runs; self.repository=repository; self.sources=sources
        self.supported_threshold=supported_threshold; self.uncertain_threshold=uncertain_threshold

    def build_from_verification(self, request:CitationBuildRequest)->CitationBundle:
        verification=self.hallucination_runs.get(tenant_id=request.tenant_id,verification_id=request.verification_id)
        if verification is None:raise LookupError("hallucination verification not found in tenant scope")
        source_run=self.source_runs.get(tenant_id=request.tenant_id,run_id=verification.self_corrective_run_id)
        if source_run is None:raise LookupError("self-corrective source run not found in tenant scope")
        contexts={x.chunk_id:x for x in source_run.final_retrieval.context}
        citations:dict[UUID,CitationRecord]={}; links:list[ClaimCitationLink]=[]; final_claims=[]
        for claim in verification.claims:
            if not claim.released_text:continue
            final_claims.append(claim)
            threshold=self.supported_threshold if claim.label is ClaimSupportLabel.SUPPORTED else self.uncertain_threshold
            for check in claim.evidence:
                if check.lexical_entailment < threshold or check.contradiction_score >= 0.65:continue
                context=contexts.get(check.chunk_id)
                if context is None:continue
                source=self.sources.resolve_chunk(tenant_id=request.tenant_id,chunk_id=check.chunk_id)
                if source is None:continue
                if source.document_id != context.document_id or source.content_hash != check.evidence_sha256:
                    continue
                locator=request.locators.get(check.chunk_id) or TextLocator(chunk_ordinal=source.chunk_ordinal)
                cid=stable_citation_id(tenant_id=request.tenant_id,document_id=source.document_id,chunk_id=source.chunk_id,source_version=context.source_version,evidence_sha256=check.evidence_sha256,locator=locator)
                citations[cid]=CitationRecord(citation_id=cid,tenant_id=request.tenant_id,document_id=source.document_id,chunk_id=source.chunk_id,source_key=source.source_key,title=source.title,source_version=context.source_version,evidence_sha256=check.evidence_sha256,locator=locator,required_permission=source.required_permission,service=source.service,environment=source.environment,team=source.team,document_kind=source.document_kind,deep_link=f"/citations/{cid}")
                links.append(ClaimCitationLink(verification_id=request.verification_id,claim_id=claim.claim_id,citation_id=cid,entailment_score=check.lexical_entailment,entails_released_claim=True,claim_qualified=claim.action is ClaimReleaseAction.QUALIFY))
        mapped={l.claim_id for l in links if l.entails_released_claim}
        all_cited=all(c.claim_id in mapped for c in final_claims)
        all_entails=all(l.entails_released_claim for l in links) and all_cited
        bundle=CitationBundle(tenant_id=request.tenant_id,verification_id=request.verification_id,citations=list(citations.values()),mappings=links,final_claim_count=len(final_claims),final_claims_cited=all_cited,all_citations_entail=all_entails,metadata={"citation_version":CITATION_VERSION,"source_run_id":str(verification.self_corrective_run_id)})
        if final_claims and not (all_cited and all_entails):
            raise ValueError("citation closure failed: every released claim requires accessible entailing source evidence")
        self.repository.save_bundle(bundle)
        return bundle

    def get_citation(self, *, tenant_id:UUID,citation_id:UUID)->CitationRecord|None:
        return self.repository.get_citation(tenant_id=tenant_id,citation_id=citation_id)

    def claim_links(self, *, tenant_id:UUID,verification_id:UUID,claim_id:str)->list[ClaimCitationLink]:
        return self.repository.list_claim_links(tenant_id=tenant_id,verification_id=verification_id,claim_id=claim_id)

    def preview(self, *, tenant_id:UUID,citation_id:UUID,authorization:RetrievalAuthorizationScope)->CitationPreview|None:
        citation=self.repository.get_citation(tenant_id=tenant_id,citation_id=citation_id)
        if citation is None:return None
        if PREVIEW_PERMISSION not in authorization.permissions or citation.required_permission not in authorization.permissions:return None
        requested=RequestedMetadataFilters(services=[citation.service] if citation.service else [],environments=[citation.environment] if citation.environment else [],teams=[citation.team] if citation.team else [],document_kinds=[citation.document_kind] if citation.document_kind else [])
        scope=build_effective_scope(authorization=authorization,requested=requested,required_permission=PREVIEW_PERMISSION)
        if scope.empty:return None
        return self.sources.preview(citation=citation,scope=scope)
