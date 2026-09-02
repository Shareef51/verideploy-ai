import os
from uuid import uuid4
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from verideploy.database.session import DatabaseManager
from verideploy.rag.access.schemas import RequestedMetadataFilters, RetrievalAuthorizationScope, build_effective_scope, READ_PERMISSION
from verideploy.rag.retrieval.repository import PostgresHybridRetrievalRepository

POSTGRES_URL=os.getenv("TEST_POSTGRES_URL")
pytestmark=pytest.mark.skipif(not POSTGRES_URL,reason="TEST_POSTGRES_URL is not configured")

def test_postgres_metadata_scope_never_widens_keyword_results():
    assert POSTGRES_URL
    cfg=Config("alembic.ini"); cfg.set_main_option("sqlalchemy.url",POSTGRES_URL); command.upgrade(cfg,"head")
    engine=create_engine(POSTGRES_URL,future=True); tenant=uuid4(); other=uuid4()
    with engine.begin() as c:
        for t,name in ((tenant,"a"),(other,"b")):
            c.execute(text("INSERT INTO tenants(tenant_id,slug,display_name) VALUES(:id,:slug,:name) ON CONFLICT DO NOTHING"),{"id":str(t),"slug":f"{name}-{t}","name":name})
        c.execute(text("SELECT set_config('app.tenant_id',:t,true)"),{"t":str(tenant)})
        for i,(service,team,severity,perm) in enumerate((("checkout","commerce","sev1","retrieval.read"),("ledger","finance","sev2","retrieval.read"),("checkout","commerce","sev1","restricted.read"))):
            doc,chunk=uuid4(),uuid4()
            c.execute(text("INSERT INTO retrieval_documents(document_id,tenant_id,source_key,title,service,environment,document_kind,severity,team,occurred_at,required_permission) VALUES(:d,:t,:s,:title,:service,'production','runbook',:sev,:team,now(),:perm)"),{"d":str(doc),"t":str(tenant),"s":f"{i}-{doc}","title":"pool runbook","service":service,"sev":severity,"team":team,"perm":perm})
            c.execute(text("INSERT INTO retrieval_chunks(chunk_id,tenant_id,document_id,ordinal,content,content_hash) VALUES(:c,:t,:d,0,'database pool recovery checkout ledger',:h)"),{"c":str(chunk),"t":str(tenant),"d":str(doc),"h":str(i+1)*64})
    auth=RetrievalAuthorizationScope(tenant_id=tenant,permissions=frozenset({READ_PERMISSION}),allowed_services=frozenset({"checkout"}),allowed_teams=frozenset({"commerce"}))
    scope=build_effective_scope(authorization=auth,requested=RequestedMetadataFilters(services=["checkout"],teams=["commerce"],severities=["sev1"]))
    rows=PostgresHybridRetrievalRepository(DatabaseManager(POSTGRES_URL)).keyword_search(tenant_id=tenant,query="database pool",limit=10,effective_scope=scope)
    assert len(rows)==1
    disjoint=build_effective_scope(authorization=auth,requested=RequestedMetadataFilters(services=["ledger"]))
    assert disjoint.empty
    assert PostgresHybridRetrievalRepository(DatabaseManager(POSTGRES_URL)).keyword_search(tenant_id=tenant,query="database pool",limit=10,effective_scope=disjoint)==[]
