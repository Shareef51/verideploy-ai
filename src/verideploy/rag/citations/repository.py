from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from sqlalchemy import text

from verideploy.database.session import DatabaseManager
from verideploy.rag.access.schemas import EffectiveRetrievalScope
from .schemas import CitationBundle, CitationPreview, CitationRecord, ClaimCitationLink


@dataclass(frozen=True)
class CitationSource:
    tenant_id: UUID
    document_id: UUID
    chunk_id: UUID
    source_key: str
    title: str
    content: str
    content_hash: str
    chunk_ordinal: int
    required_permission: str
    service: str | None
    environment: str | None
    team: str | None
    document_kind: str | None


class CitationRepository(Protocol):
    def save_bundle(self, bundle: CitationBundle) -> None: ...
    def get_citation(self, *, tenant_id: UUID, citation_id: UUID) -> CitationRecord | None: ...
    def list_claim_links(self, *, tenant_id: UUID, verification_id: UUID, claim_id: str) -> list[ClaimCitationLink]: ...


class CitationSourceRepository(Protocol):
    def resolve_chunk(self, *, tenant_id: UUID, chunk_id: UUID) -> CitationSource | None: ...
    def preview(self, *, citation: CitationRecord, scope: EffectiveRetrievalScope, max_chars: int = 2000) -> CitationPreview | None: ...


class InMemoryCitationRepository:
    def __init__(self) -> None:
        self._citations: dict[tuple[UUID, UUID], CitationRecord] = {}
        self._links: list[tuple[UUID, ClaimCitationLink]] = []

    def save_bundle(self, bundle: CitationBundle) -> None:
        for citation in bundle.citations:
            self._citations[(bundle.tenant_id, citation.citation_id)] = copy.deepcopy(citation)
        existing={(t,l.verification_id,l.claim_id,l.citation_id) for t,l in self._links}
        for link in bundle.mappings:
            key=(bundle.tenant_id,link.verification_id,link.claim_id,link.citation_id)
            if key not in existing:
                self._links.append((bundle.tenant_id, copy.deepcopy(link))); existing.add(key)

    def get_citation(self, *, tenant_id: UUID, citation_id: UUID) -> CitationRecord | None:
        item=self._citations.get((tenant_id,citation_id))
        return copy.deepcopy(item) if item else None

    def list_claim_links(self, *, tenant_id: UUID, verification_id: UUID, claim_id: str) -> list[ClaimCitationLink]:
        return [copy.deepcopy(l) for t,l in self._links if t==tenant_id and l.verification_id==verification_id and l.claim_id==claim_id]


class InMemoryCitationSourceRepository:
    def __init__(self, sources: list[CitationSource]) -> None:
        self._items={(s.tenant_id,s.chunk_id):s for s in sources}

    def resolve_chunk(self, *, tenant_id: UUID, chunk_id: UUID) -> CitationSource | None:
        return self._items.get((tenant_id,chunk_id))

    def preview(self, *, citation: CitationRecord, scope: EffectiveRetrievalScope, max_chars: int = 2000) -> CitationPreview | None:
        if scope.empty or citation.required_permission not in scope.permissions:
            return None
        source=self._items.get((citation.tenant_id,citation.chunk_id))
        if source is None:return None
        if scope.services is not None and (source.service or "").casefold() not in scope.services:return None
        if scope.environments is not None and (source.environment or "").casefold() not in scope.environments:return None
        if scope.teams is not None and (source.team or "").casefold() not in scope.teams:return None
        if scope.document_kinds is not None and (source.document_kind or "").casefold() not in scope.document_kinds:return None
        return CitationPreview(citation=citation,excerpt=source.content[:max_chars])


class PostgresCitationRepository:
    def __init__(self, db: DatabaseManager) -> None:self.db=db

    def save_bundle(self, bundle: CitationBundle) -> None:
        with self.db.transaction(bundle.tenant_id) as s:
            for c in bundle.citations:
                s.execute(text("""INSERT INTO citations
                    (citation_id,tenant_id,document_id,chunk_id,source_key,title,source_version,evidence_sha256,locator_kind,locator_json,required_permission,service,environment,team,document_kind,deep_link)
                    VALUES (:id,:tenant,:document,:chunk,:source,:title,:version,:sha,:kind,CAST(:locator AS jsonb),:perm,:service,:env,:team,:doc_kind,:link)
                    ON CONFLICT (citation_id) DO NOTHING"""),{
                    "id":str(c.citation_id),"tenant":str(c.tenant_id),"document":str(c.document_id),"chunk":str(c.chunk_id),"source":c.source_key,
                    "title":c.title,"version":c.source_version,"sha":c.evidence_sha256,"kind":c.locator.kind,"locator":json.dumps(c.locator.model_dump(mode="json"),sort_keys=True),
                    "perm":c.required_permission,"service":c.service,"env":c.environment,"team":c.team,"doc_kind":c.document_kind,"link":c.deep_link})
            for l in bundle.mappings:
                s.execute(text("""INSERT INTO claim_citations
                    (tenant_id,verification_id,claim_id,citation_id,entailment_score,entails_released_claim,claim_qualified)
                    VALUES (:tenant,:verification,:claim,:citation,:score,:entails,:qualified)
                    ON CONFLICT DO NOTHING"""),{"tenant":str(bundle.tenant_id),"verification":str(l.verification_id),"claim":l.claim_id,"citation":str(l.citation_id),"score":l.entailment_score,"entails":l.entails_released_claim,"qualified":l.claim_qualified})

    @staticmethod
    def _record(row) -> CitationRecord:
        return CitationRecord(citation_id=row["citation_id"],tenant_id=row["tenant_id"],document_id=row["document_id"],chunk_id=row["chunk_id"],source_key=row["source_key"],title=row["title"],source_version=row["source_version"],evidence_sha256=row["evidence_sha256"],locator=row["locator_json"],required_permission=row["required_permission"],service=row["service"],environment=row["environment"],team=row["team"],document_kind=row["document_kind"],deep_link=row["deep_link"])

    def get_citation(self, *, tenant_id: UUID, citation_id: UUID) -> CitationRecord | None:
        with self.db.transaction(tenant_id) as s:
            row=s.execute(text("SELECT * FROM citations WHERE tenant_id=:tenant AND citation_id=:id"),{"tenant":str(tenant_id),"id":str(citation_id)}).mappings().first()
        return self._record(row) if row else None

    def list_claim_links(self, *, tenant_id: UUID, verification_id: UUID, claim_id: str) -> list[ClaimCitationLink]:
        with self.db.transaction(tenant_id) as s:
            rows=s.execute(text("""SELECT verification_id,claim_id,citation_id,entailment_score,entails_released_claim,claim_qualified
                FROM claim_citations WHERE tenant_id=:tenant AND verification_id=:verification AND claim_id=:claim ORDER BY citation_id"""),{"tenant":str(tenant_id),"verification":str(verification_id),"claim":claim_id}).mappings().all()
        return [ClaimCitationLink(**dict(r)) for r in rows]


class PostgresCitationSourceRepository:
    def __init__(self, db: DatabaseManager) -> None:self.db=db

    def resolve_chunk(self, *, tenant_id: UUID, chunk_id: UUID) -> CitationSource | None:
        with self.db.transaction(tenant_id) as s:
            r=s.execute(text("""SELECT d.tenant_id,d.document_id,c.chunk_id,d.source_key,d.title,c.content,c.content_hash,c.ordinal,
                d.required_permission,d.service,d.environment,d.team,d.document_kind
                FROM retrieval_chunks c JOIN retrieval_documents d ON d.document_id=c.document_id AND d.tenant_id=c.tenant_id
                WHERE c.tenant_id=:tenant AND c.chunk_id=:chunk"""),{"tenant":str(tenant_id),"chunk":str(chunk_id)}).mappings().first()
        return CitationSource(**dict(r)) if r else None

    def preview(self, *, citation: CitationRecord, scope: EffectiveRetrievalScope, max_chars: int = 2000) -> CitationPreview | None:
        if scope.empty or citation.required_permission not in scope.permissions:return None
        sql=text("""SELECT left(c.content,:max_chars) content FROM citations x
            JOIN retrieval_chunks c ON c.chunk_id=x.chunk_id AND c.tenant_id=x.tenant_id
            JOIN retrieval_documents d ON d.document_id=x.document_id AND d.tenant_id=x.tenant_id
            WHERE x.tenant_id=:tenant AND x.citation_id=:citation
              AND (:services IS NULL OR d.service=ANY(CAST(:services AS text[])))
              AND (:envs IS NULL OR d.environment=ANY(CAST(:envs AS text[])))
              AND (:kinds IS NULL OR d.document_kind=ANY(CAST(:kinds AS text[])))
              AND (:teams IS NULL OR d.team=ANY(CAST(:teams AS text[])))
              AND d.required_permission=ANY(CAST(:permissions AS text[]))""")
        params={"max_chars":max_chars,"tenant":str(citation.tenant_id),"citation":str(citation.citation_id),"services":list(scope.services) if scope.services is not None else None,"envs":list(scope.environments) if scope.environments is not None else None,"kinds":list(scope.document_kinds) if scope.document_kinds is not None else None,"teams":list(scope.teams) if scope.teams is not None else None,"permissions":list(scope.permissions)}
        with self.db.transaction(citation.tenant_id) as s:r=s.execute(sql,params).scalar_one_or_none()
        return CitationPreview(citation=citation,excerpt=r) if r is not None else None
