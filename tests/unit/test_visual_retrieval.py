from __future__ import annotations
from pathlib import Path
from uuid import uuid4
import fitz, pytest
from fastapi.testclient import TestClient
from verideploy.rag.visual_retrieval.rendering import PdfPageRenderer
from verideploy.rag.visual_retrieval.providers import CpuVisualFallbackAdapter, ColPaliAdapter
from verideploy.rag.visual_retrieval.service import VisualDocumentService
from verideploy.rag.visual_retrieval.schemas import VisualSearchQuery,VisualIndexRecord,VisualBackend

class MemoryRepo:
    def __init__(self): self.pages={};self.index=[]
    def save_page(self,p): self.pages[p.page_id]=p
    def save_index(self,r): self.index.append(r)
    def list_indexed_pages(self,*,tenant_id,backend,model_name,document_id=None):
        out=[]
        for r in self.index:
            p=self.pages[r.page_id]
            if p.tenant_id!=tenant_id or r.backend!=backend or r.model_name!=model_name:continue
            if document_id and p.document_id!=document_id:continue
            out.append({"page_id":p.page_id,"document_id":p.document_id,"page_number":p.page_number,"image_path":p.image_path,"image_sha256":p.image_sha256,"feature_json":r.feature_vector,"embedding_ref":r.embedding_ref})
        return out

def make_pdf()->bytes:
    doc=fitz.open()
    pages=[
      ("Executive Overview","NexusPay release assurance platform general overview"),
      ("Architecture Dependency Topology","payment-service connects to Redis and PostgreSQL through checkout-service dependency path"),
      ("Grafana Checkout Dashboard","checkout latency p95 spike error rate metric dashboard chart"),
      ("Incident Runbook","rollback procedure and operator checklist")]
    for title,body in pages:
        p=doc.new_page(width=700,height=500);p.insert_text((50,60),title,fontsize=24);p.insert_textbox((50,100,650,220),body,fontsize=15)
        if "Architecture" in title:
            for x in (60,250,440): p.draw_rect(fitz.Rect(x,280,x+130,350),color=(0,0,0));
            p.draw_line((190,315),(250,315),color=(0,0,0));p.draw_line((380,315),(440,315),color=(0,0,0))
        if "Dashboard" in title:
            for i,h in enumerate((40,90,60,130,80)): p.draw_rect(fitz.Rect(80+i*90,420-h,130+i*90,420),color=(0.1,0.3,0.8),fill=(0.1,0.3,0.8))
    data=doc.tobytes();doc.close();return data

def test_renderer_and_cpu_search(tmp_path:Path):
    tenant,docid=uuid4(),uuid4(); pages=PdfPageRenderer(tmp_path,dpi=96).render(tenant_id=tenant,document_id=docid,pdf_bytes=make_pdf())
    assert len(pages)==4 and all(Path(p.image_path).exists() for p in pages)
    repo=MemoryRepo();svc=VisualDocumentService(repository=repo,adapter=CpuVisualFallbackAdapter());svc.index_pages(pages)
    arch=svc.search(VisualSearchQuery(tenant_id=tenant,text="architecture payment service Redis PostgreSQL dependency topology",top_k=2))
    dash=svc.search(VisualSearchQuery(tenant_id=tenant,text="Grafana dashboard checkout latency p95 chart",top_k=2))
    assert arch.hits[0].page_number==2
    assert dash.hits[0].page_number==3
    assert arch.backend is VisualBackend.CPU_FALLBACK

def test_tenant_isolation(tmp_path:Path):
    repo=MemoryRepo();adapter=CpuVisualFallbackAdapter();svc=VisualDocumentService(repository=repo,adapter=adapter)
    ta,tb,da,db=uuid4(),uuid4(),uuid4(),uuid4()
    pa=PdfPageRenderer(tmp_path/'a',dpi=72).render(tenant_id=ta,document_id=da,pdf_bytes=make_pdf())
    pb=PdfPageRenderer(tmp_path/'b',dpi=72).render(tenant_id=tb,document_id=db,pdf_bytes=make_pdf())
    svc.index_pages(pa+pb)
    result=svc.search(VisualSearchQuery(tenant_id=ta,text="Grafana dashboard",top_k=10))
    assert result.hits and {x.document_id for x in result.hits}=={da}

def test_renderer_rejects_non_pdf(tmp_path:Path):
    with pytest.raises(ValueError): PdfPageRenderer(tmp_path).render(tenant_id=uuid4(),document_id=uuid4(),pdf_bytes=b"not a pdf")

def test_colpali_dependency_is_optional():
    try: import transformers  # noqa
    except ImportError:
        with pytest.raises(RuntimeError): ColPaliAdapter()

def test_migration_contract():
    text=Path('src/verideploy/database/migrations/versions/0003_visual_document_retrieval.py').read_text()
    for marker in ('visual_documents','visual_pages','visual_page_indexes','ENABLE ROW LEVEL SECURITY','FORCE ROW LEVEL SECURITY'):
        assert marker in text

def test_visual_route_auth_and_tenant(monkeypatch):
    from services.ai.main import app
    from services.ai.visual_retrieval import get_visual_retrieval_service
    tenant=uuid4()
    class S:
        def search(self,q):
            from verideploy.rag.visual_retrieval.schemas import VisualSearchResult
            return VisualSearchResult(backend=VisualBackend.CPU_FALLBACK,model_name='test',hits=[])
    app.dependency_overrides[get_visual_retrieval_service]=lambda:S()
    c=TestClient(app)
    payload={"tenant_id":str(tenant),"text":"architecture","top_k":3}
    assert c.post('/internal/v1/retrieval/visual',json=payload).status_code==401
    assert c.post('/internal/v1/retrieval/visual',json=payload,headers={'x-internal-service':'verideploy-gateway','x-tenant-id':str(uuid4())}).status_code==403
    assert c.post('/internal/v1/retrieval/visual',json=payload,headers={'x-internal-service':'verideploy-gateway','x-tenant-id':str(tenant)}).status_code==200
    app.dependency_overrides.clear()

def test_visual_index_worker_uses_same_pipeline(tmp_path:Path):
    from workers.multimodal.visual_index_worker import VisualIndexWorker,VisualIndexCommand
    tenant,docid=uuid4(),uuid4()
    class R(MemoryRepo):
        def upsert_document(self,**kwargs): self.document=kwargs
    repo=R();svc=VisualDocumentService(repository=repo,adapter=CpuVisualFallbackAdapter(),renderer=PdfPageRenderer(tmp_path,dpi=72))
    out=VisualIndexWorker(svc).handle(VisualIndexCommand(tenant,docid,'arch.pdf','Architecture',make_pdf()))
    assert out['pages_rendered']==4 and out['pages_indexed']==4 and repo.document['tenant_id']==tenant

def test_renderer_page_ids_are_stable_for_retries(tmp_path:Path):
    tenant,docid=uuid4(),uuid4();r=PdfPageRenderer(tmp_path,dpi=72)
    a=r.render(tenant_id=tenant,document_id=docid,pdf_bytes=make_pdf())
    b=r.render(tenant_id=tenant,document_id=docid,pdf_bytes=make_pdf())
    assert [x.page_id for x in a]==[x.page_id for x in b]
