from __future__ import annotations
from uuid import UUID
from pydantic import BaseModel,ConfigDict
from sqlalchemy import text
from verideploy.database.session import DatabaseManager
from .schemas import EffectiveRetrievalScope, PREVIEW_PERMISSION
class SourcePreview(BaseModel):
    model_config=ConfigDict(extra="forbid")
    document_id:UUID; source_key:str; title:str; content:str; service:str|None=None; environment:str|None=None; document_kind:str; severity:str|None=None; team:str|None=None
class PostgresSourcePreviewRepository:
    def __init__(self,db:DatabaseManager):self.db=db
    def preview(self,*,document_id:UUID,scope:EffectiveRetrievalScope,max_chars:int=2000)->SourcePreview|None:
        if scope.empty or PREVIEW_PERMISSION not in scope.permissions:return None
        sql=text("""SELECT d.document_id,d.source_key,d.title,d.service,d.environment,d.document_kind,d.severity,d.team,left(string_agg(c.content,E'\\n' ORDER BY c.ordinal),:max_chars) content FROM retrieval_documents d JOIN retrieval_chunks c ON c.document_id=d.document_id AND c.tenant_id=d.tenant_id WHERE d.tenant_id=:tenant AND d.document_id=:doc AND (:services IS NULL OR d.service=ANY(CAST(:services AS text[]))) AND (:envs IS NULL OR d.environment=ANY(CAST(:envs AS text[]))) AND (:kinds IS NULL OR d.document_kind=ANY(CAST(:kinds AS text[]))) AND (:sevs IS NULL OR d.severity=ANY(CAST(:sevs AS text[]))) AND (:teams IS NULL OR d.team=ANY(CAST(:teams AS text[]))) AND (:from_ts IS NULL OR d.occurred_at>=:from_ts) AND (:to_ts IS NULL OR d.occurred_at<=:to_ts) AND d.required_permission=ANY(CAST(:permissions AS text[])) GROUP BY d.document_id""")
        p={"tenant":str(scope.tenant_id),"doc":str(document_id),"max_chars":max_chars,"services":list(scope.services) if scope.services is not None else None,"envs":list(scope.environments) if scope.environments is not None else None,"kinds":[x.value for x in scope.document_kinds] if scope.document_kinds is not None else None,"sevs":list(scope.severities) if scope.severities is not None else None,"teams":list(scope.teams) if scope.teams is not None else None,"from_ts":scope.occurred_from,"to_ts":scope.occurred_to,"permissions":list(scope.permissions)}
        with self.db.tenant_session(scope.tenant_id) as s:r=s.execute(sql,p).mappings().first()
        return SourcePreview(**dict(r)) if r else None
