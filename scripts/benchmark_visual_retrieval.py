from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4
import json,fitz
from verideploy.rag.visual_retrieval.rendering import PdfPageRenderer
from verideploy.rag.visual_retrieval.providers import CpuVisualFallbackAdapter
from verideploy.rag.visual_retrieval.schemas import VisualSearchQuery
from verideploy.rag.visual_retrieval.service import VisualDocumentService
from verideploy.rag.visual_retrieval.benchmark import VisualCase,ndcg_at_k
class Repo:
 def __init__(self):self.p={};self.i=[]
 def save_page(self,p):self.p[p.page_id]=p
 def save_index(self,r):self.i.append(r)
 def list_indexed_pages(self,*,tenant_id,backend,model_name,document_id=None):
  return [{"page_id":p.page_id,"document_id":p.document_id,"page_number":p.page_number,"image_path":p.image_path,"image_sha256":p.image_sha256,"feature_json":r.feature_vector,"embedding_ref":r.embedding_ref} for r in self.i for p in [self.p[r.page_id]] if p.tenant_id==tenant_id and r.backend==backend and r.model_name==model_name]
def pdf():
 d=fitz.open();spec=[('Overview','release platform summary'),('Architecture','payment-service Redis PostgreSQL dependency topology diagram'),('Dashboard','Grafana checkout latency p95 error rate dashboard chart'),('Table','service ownership table matrix')]
 for title,txt in spec:
  p=d.new_page(width=700,height=500);p.insert_text((40,60),title,fontsize=26);p.insert_textbox((40,100,660,200),txt,fontsize=16)
  if title=='Architecture':
   for x in (80,280,480):p.draw_rect(fitz.Rect(x,280,x+120,340),color=(0,0,0));
  if title=='Dashboard':
   for i,h in enumerate((30,80,50,120)):p.draw_rect(fitz.Rect(100+i*110,430-h,160+i*110,430),fill=(0.2,0.4,0.8))
 b=d.tobytes();d.close();return b
with TemporaryDirectory() as td:
 t,di=uuid4(),uuid4();pages=PdfPageRenderer(td,dpi=96).render(tenant_id=t,document_id=di,pdf_bytes=pdf());svc=VisualDocumentService(repository=Repo(),adapter=CpuVisualFallbackAdapter());svc.index_pages(pages)
 cases=[VisualCase('architecture payment-service Redis PostgreSQL dependency diagram',2),VisualCase('Grafana checkout latency p95 dashboard chart',3)]
 scores=[];rows=[]
 for c in cases:
  r=svc.search(VisualSearchQuery(tenant_id=t,text=c.query,top_k=4));rank=[h.page_number for h in r.hits];n=ndcg_at_k(rank,c.relevant_page,4);scores.append(n);rows.append({'query':c.query,'relevant_page':c.relevant_page,'ranking':rank,'ndcg@4':n})
 result={'backend':'cpu_fallback','cases':rows,'ndcg@4':sum(scores)/len(scores),'gate':sum(scores)/len(scores)>=0.95}
 Path('artifacts/benchmark.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2));raise SystemExit(0 if result['gate'] else 1)
