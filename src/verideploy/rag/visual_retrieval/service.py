from __future__ import annotations
from pathlib import Path
import json, numpy as np
from verideploy.rag.visual_retrieval.providers import VisualRetrieverAdapter, CpuVisualFallbackAdapter
from verideploy.rag.visual_retrieval.rendering import PdfPageRenderer
from verideploy.rag.visual_retrieval.repository import PostgresVisualPageRepository
from verideploy.rag.visual_retrieval.schemas import *
from verideploy.rag.access.schemas import RetrievalAuthorizationScope, build_effective_scope, VISUAL_PERMISSION

class VisualDocumentService:
    def __init__(self,*,repository:PostgresVisualPageRepository,adapter:VisualRetrieverAdapter,renderer:PdfPageRenderer|None=None,index_root:str|Path="data/processed/visual_index",index_version:str="v1") -> None:
        self.repository=repository;self.adapter=adapter;self.renderer=renderer;self.index_root=Path(index_root);self.index_version=index_version
    def index_pdf(self, *, tenant_id, document_id, source_key:str, title:str, pdf_bytes:bytes, service:str|None=None, environment:str|None=None, document_kind:str="general", severity:str|None=None, team:str|None=None, occurred_at=None, required_permission:str="retrieval.visual.read"):
        if self.renderer is None: raise RuntimeError("PDF renderer is not configured")
        self.repository.upsert_document(tenant_id=tenant_id,document_id=document_id,source_key=source_key,title=title,service=service,environment=environment,document_kind=document_kind,severity=severity,team=team,occurred_at=occurred_at,required_permission=required_permission)
        pages=self.renderer.render(tenant_id=tenant_id,document_id=document_id,pdf_bytes=pdf_bytes)
        return pages,self.index_pages(pages)
    def index_pages(self,pages:list[RenderedPage])->list[VisualIndexRecord]:
        records=[]
        for page in pages:
            self.repository.save_page(page)
            encoded=self.adapter.index_page(page)
            if isinstance(self.adapter,CpuVisualFallbackAdapter):
                rec=VisualIndexRecord(page_id=page.page_id,tenant_id=page.tenant_id,backend=self.adapter.backend,model_name=self.adapter.model_name,index_version=self.index_version,feature_vector=list(encoded))
            else:
                self.index_root.mkdir(parents=True,exist_ok=True); path=self.index_root/f"{page.tenant_id}-{page.page_id}.npy"; np.save(path,encoded.numpy() if hasattr(encoded,'numpy') else encoded)
                rec=VisualIndexRecord(page_id=page.page_id,tenant_id=page.tenant_id,backend=self.adapter.backend,model_name=self.adapter.model_name,index_version=self.index_version,embedding_ref=str(path))
            self.repository.save_index(rec);records.append(rec)
        return records
    def search(self,q:VisualSearchQuery,*,authorization:RetrievalAuthorizationScope|None=None)->VisualSearchResult:
        authorization=authorization or RetrievalAuthorizationScope(tenant_id=q.tenant_id,permissions=frozenset({VISUAL_PERMISSION}))
        if authorization.tenant_id!=q.tenant_id: raise PermissionError("visual retrieval authorization tenant mismatch")
        scope=build_effective_scope(authorization=authorization,requested=q.metadata_filters,required_permission=VISUAL_PERMISSION)
        kwargs={"tenant_id":q.tenant_id,"backend":self.adapter.backend,"model_name":self.adapter.model_name,"document_id":q.document_id}
        if getattr(self.repository,"supports_scope",False): kwargs["effective_scope"]=scope
        rows=self.repository.list_indexed_pages(**kwargs)
        hits=[]
        for row in rows:
            if self.adapter.backend is VisualBackend.CPU_FALLBACK: idx=list(row["feature_json"] or [])
            else: idx=np.load(row["embedding_ref"],allow_pickle=False)
            score=self.adapter.score(q.text,idx)
            hits.append(VisualSearchHit(page_id=row["page_id"],document_id=row["document_id"],page_number=row["page_number"],score=score,backend=self.adapter.backend,model_name=self.adapter.model_name,image_path=row["image_path"],image_sha256=row["image_sha256"]))
        hits.sort(key=lambda x:(-x.score,x.page_number,str(x.page_id)))
        return VisualSearchResult(backend=self.adapter.backend,model_name=self.adapter.model_name,hits=hits[:q.top_k])
