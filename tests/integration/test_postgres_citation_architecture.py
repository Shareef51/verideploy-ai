from __future__ import annotations
import os,json,hashlib
from uuid import UUID,uuid4
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from verideploy.database.session import DatabaseManager
from verideploy.rag.citations.repository import PostgresCitationRepository
from verideploy.rag.citations.schemas import CitationBundle,CitationRecord,ClaimCitationLink,TextLocator
from verideploy.rag.citations.service import stable_citation_id

URL=os.getenv("TEST_POSTGRES_URL")
pytestmark=pytest.mark.skipif(not URL,reason="TEST_POSTGRES_URL is not configured")
TENANT=UUID("11111111-1111-4111-8111-111111111111"); OTHER=UUID("22222222-2222-4222-8222-222222222222")

def test_postgres_citations_are_tenant_scoped_append_only_and_mapped():
    assert URL
    cfg=Config("alembic.ini");cfg.set_main_option("sqlalchemy.url",URL);command.upgrade(cfg,"head")
    db=DatabaseManager(URL);doc=uuid4();chunk=uuid4();source_run=uuid4();verification=uuid4();content="Checkout pool exhaustion caused latency.";sha=hashlib.sha256(content.encode()).hexdigest();version="a"*64
    try:
        with db.engine.begin() as conn:
            for tenant,slug in ((TENANT,"postgres-citation-architecture"),(OTHER,"other")):
                conn.execute(text("INSERT INTO tenants (tenant_id,slug,display_name) VALUES (:id,:slug,:name) ON CONFLICT (tenant_id) DO NOTHING"),{"id":str(tenant),"slug":f"{slug}-{str(tenant)[:8]}","name":slug})
        with db.session(tenant_id=TENANT) as s:
            s.execute(text("""INSERT INTO retrieval_documents(document_id,tenant_id,source_key,title,service,environment,document_kind,severity,team,occurred_at,required_permission)
                VALUES(:doc,:tenant,'runbook://',' runbook','checkout','production','runbook','sev1','commerce',now(),'retrieval.read')"""),{"doc":str(doc),"tenant":str(TENANT)})
            s.execute(text("INSERT INTO retrieval_chunks(chunk_id,tenant_id,document_id,ordinal,content,content_hash) VALUES(:chunk,:tenant,:doc,0,:content,:sha)"),{"chunk":str(chunk),"tenant":str(TENANT),"doc":str(doc),"content":content,"sha":sha})
            s.execute(text("INSERT INTO self_corrective_rag_runs(run_id,tenant_id,controller_version,stop_reason,answerable,qualified,result_json) VALUES(:run,:tenant,'1.0.0','sufficient_evidence',true,false,CAST(:payload AS jsonb))"),{"run":str(source_run),"tenant":str(TENANT),"payload":'{"stub":true}'})
            s.execute(text("""INSERT INTO hallucination_protection_runs(verification_id,tenant_id,self_corrective_run_id,verifier_version,protected,supported_count,uncertain_count,unsupported_count,unsupported_material_rate,prompt_injection_evidence_count,result_json)
                VALUES(:v,:tenant,:run,'1.0.0',true,1,0,0,0,0,CAST(:payload AS jsonb))"""),{"v":str(verification),"tenant":str(TENANT),"run":str(source_run),"payload":'{"stub":true}'})
        locator=TextLocator(chunk_ordinal=0);cid=stable_citation_id(tenant_id=TENANT,document_id=doc,chunk_id=chunk,source_version=version,evidence_sha256=sha,locator=locator)
        citation=CitationRecord(citation_id=cid,tenant_id=TENANT,document_id=doc,chunk_id=chunk,source_key="runbook://",title=" runbook",source_version=version,evidence_sha256=sha,locator=locator,required_permission="retrieval.read",service="checkout",environment="production",team="commerce",document_kind="runbook",deep_link=f"/citations/{cid}")
        link=ClaimCitationLink(verification_id=verification,claim_id="c1",citation_id=cid,entailment_score=.9,entails_released_claim=True)
        repo=PostgresCitationRepository(db);repo.save_bundle(CitationBundle(tenant_id=TENANT,verification_id=verification,citations=[citation],mappings=[link],final_claim_count=1,final_claims_cited=True,all_citations_entail=True))
        assert repo.get_citation(tenant_id=TENANT,citation_id=cid)==citation
        assert repo.get_citation(tenant_id=OTHER,citation_id=cid) is None
        assert repo.list_claim_links(tenant_id=TENANT,verification_id=verification,claim_id="c1")==[link]
        with pytest.raises(DBAPIError):
            with db.session(tenant_id=TENANT) as s:s.execute(text("UPDATE citations SET title='mutated' WHERE citation_id=:id"),{"id":str(cid)})
    finally:db.dispose()
