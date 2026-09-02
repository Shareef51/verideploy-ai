from __future__ import annotations
import json
from uuid import UUID
from sqlalchemy import text
from verideploy.database.session import DatabaseManager
from verideploy.rag.visual_retrieval.schemas import RenderedPage, VisualBackend, VisualIndexRecord

class PostgresVisualPageRepository:
    supports_scope=True
    def __init__(self, db: DatabaseManager) -> None:
        if db.engine.dialect.name != "postgresql": raise ValueError("PostgreSQL required")
        self.db=db
    def upsert_document(self, *, tenant_id: UUID, document_id: UUID, source_key: str, title: str, service: str|None=None, environment: str|None=None, document_kind: str="general", severity: str|None=None, team: str|None=None, occurred_at=None, required_permission: str="retrieval.visual.read") -> None:
        sql=text("INSERT INTO visual_documents(document_id,tenant_id,source_key,title,service,environment,document_kind,severity,team,occurred_at,required_permission) VALUES(:d,:t,:s,:title,:service,:environment,:kind,:severity,:team,:occurred_at,:permission) ON CONFLICT(document_id) DO UPDATE SET title=EXCLUDED.title,service=EXCLUDED.service,environment=EXCLUDED.environment,document_kind=EXCLUDED.document_kind,severity=EXCLUDED.severity,team=EXCLUDED.team,occurred_at=EXCLUDED.occurred_at,required_permission=EXCLUDED.required_permission")
        with self.db.tenant_session(tenant_id) as s: s.execute(sql,{"d":str(document_id),"t":str(tenant_id),"s":source_key,"title":title,"service":service,"environment":environment,"kind":document_kind,"severity":severity,"team":team,"occurred_at":occurred_at,"permission":required_permission})
    def save_page(self,page:RenderedPage)->None:
        sql=text("INSERT INTO visual_pages(page_id,tenant_id,document_id,page_number,image_path,image_sha256,width,height,native_text) VALUES(:p,:t,:d,:n,:path,:sha,:w,:h,:txt) ON CONFLICT(tenant_id,document_id,page_number) DO UPDATE SET image_path=EXCLUDED.image_path,image_sha256=EXCLUDED.image_sha256,width=EXCLUDED.width,height=EXCLUDED.height,native_text=EXCLUDED.native_text")
        with self.db.tenant_session(page.tenant_id) as s:s.execute(sql,{"p":str(page.page_id),"t":str(page.tenant_id),"d":str(page.document_id),"n":page.page_number,"path":page.image_path,"sha":page.image_sha256,"w":page.width,"h":page.height,"txt":page.native_text})
    def save_index(self,record:VisualIndexRecord)->None:
        sql=text("INSERT INTO visual_page_indexes(index_id,tenant_id,page_id,backend,model_name,index_version,embedding_ref,feature_json) VALUES(:i,:t,:p,:b,:m,:v,:r,CAST(:f AS json)) ON CONFLICT(tenant_id,page_id,backend,model_name,index_version) DO UPDATE SET embedding_ref=EXCLUDED.embedding_ref,feature_json=EXCLUDED.feature_json")
        with self.db.tenant_session(record.tenant_id) as s:s.execute(sql,{"i":str(record.index_id),"t":str(record.tenant_id),"p":str(record.page_id),"b":record.backend.value,"m":record.model_name,"v":record.index_version,"r":record.embedding_ref,"f":json.dumps(record.feature_vector) if record.feature_vector is not None else "null"})
    def list_indexed_pages(self,*,tenant_id:UUID,backend:VisualBackend,model_name:str,document_id:UUID|None=None,effective_scope=None):
        if effective_scope is not None and effective_scope.empty:return []
        sql=text("""SELECT p.*,i.feature_json,i.embedding_ref FROM visual_pages p JOIN visual_page_indexes i ON i.page_id=p.page_id AND i.tenant_id=p.tenant_id JOIN visual_documents d ON d.document_id=p.document_id AND d.tenant_id=p.tenant_id WHERE p.tenant_id=:t AND i.backend=:b AND i.model_name=:m AND (:d IS NULL OR p.document_id=:d) AND (:services IS NULL OR d.service=ANY(CAST(:services AS text[]))) AND (:envs IS NULL OR d.environment=ANY(CAST(:envs AS text[]))) AND (:kinds IS NULL OR d.document_kind=ANY(CAST(:kinds AS text[]))) AND (:sevs IS NULL OR d.severity=ANY(CAST(:sevs AS text[]))) AND (:teams IS NULL OR d.team=ANY(CAST(:teams AS text[]))) AND (:from_ts IS NULL OR d.occurred_at>=:from_ts) AND (:to_ts IS NULL OR d.occurred_at<=:to_ts) AND d.required_permission=ANY(CAST(:permissions AS text[])) ORDER BY p.document_id,p.page_number""")
        params={"t":str(tenant_id),"b":backend.value,"m":model_name,"d":str(document_id) if document_id else None,"services":list(effective_scope.services) if effective_scope and effective_scope.services is not None else None,"envs":list(effective_scope.environments) if effective_scope and effective_scope.environments is not None else None,"kinds":list(effective_scope.document_kinds) if effective_scope and effective_scope.document_kinds is not None else None,"sevs":list(effective_scope.severities) if effective_scope and effective_scope.severities is not None else None,"teams":list(effective_scope.teams) if effective_scope and effective_scope.teams is not None else None,"from_ts":effective_scope.occurred_from if effective_scope else None,"to_ts":effective_scope.occurred_to if effective_scope else None,"permissions":list(effective_scope.permissions) if effective_scope else ["retrieval.visual.read"]}
        with self.db.tenant_session(tenant_id) as s:return list(s.execute(sql,params).mappings())
