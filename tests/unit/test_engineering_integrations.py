from __future__ import annotations
from datetime import datetime, timezone
import httpx, pytest
from verideploy.integrations.adapters import GitHubIntegration, JiraIntegration, RangeIntegration, SyntheticIntegrationBundle
from verideploy.integrations.contracts import IntegrationStatus, IntegrationType
from verideploy.integrations.errors import IntegrationHostDenied
from verideploy.integrations.http import HTTPIntegrationPolicy, ResilientReadClient

@pytest.mark.asyncio
async def test_github_link_pagination_is_bounded_and_preserves_secret_isolation():
    seen=[]
    def handler(req):
        seen.append(req)
        assert req.headers.get("authorization") == "Bearer secret-token"
        page=req.url.params.get("page") or "1"
        if page == "1":
            return httpx.Response(200,json=[{"id":1,"number":1}],headers={"Link":'<https://api.github.com/repos/o/r/pulls?state=all&per_page=1&page=2>; rel="next"'})
        return httpx.Response(200,json=[{"id":2,"number":2}])
    gh=GitHubIntegration(base_url="https://api.github.com",token="secret-token",transport=httpx.MockTransport(handler),policy=HTTPIntegrationPolicy(max_requests=4))
    result=await gh.list_pull_requests("o","r",per_page=1,max_pages=2)
    assert result.status is IntegrationStatus.OK and [x.source_id for x in result.records]==["1","2"] and result.pages_fetched==2
    assert "secret-token" not in result.model_dump_json()

@pytest.mark.asyncio
async def test_github_retry_after_is_bounded():
    calls=0
    def handler(req):
        nonlocal calls; calls+=1
        if calls==1: return httpx.Response(429,headers={"Retry-After":"0"},json={"message":"rate limit"})
        return httpx.Response(200,json={"id":1,"name":"r"})
    gh=GitHubIntegration(base_url="https://api.github.com",token="t",transport=httpx.MockTransport(handler),policy=HTTPIntegrationPolicy(max_attempts=2,max_requests=2,backoff_base_seconds=0))
    data=await gh.repository_get("o","r")
    assert data["id"]==1 and calls==2

@pytest.mark.asyncio
async def test_jira_next_page_token_pagination():
    calls=[]
    def handler(req):
        calls.append(req.url.params.get("nextPageToken"))
        if len(calls)==1: return httpx.Response(200,json={"issues":[{"id":"1","key":"OPS-1"}],"isLast":False,"nextPageToken":"N2"})
        return httpx.Response(200,json={"issues":[{"id":"2","key":"OPS-2"}],"isLast":True})
    jira=JiraIntegration(base_url="https://acme.atlassian.net",token="j",email="ops@example.com",auth_mode="basic",allowed_hosts={"acme.atlassian.net"},transport=httpx.MockTransport(handler))
    result=await jira.search_issues('project = OPS',max_pages=5)
    assert result.status is IntegrationStatus.OK and len(result.records)==2 and calls==[None,"N2"]

@pytest.mark.asyncio
async def test_unconfigured_integration_is_explicit_not_empty_success():
    jira=JiraIntegration(base_url=None,token=None,allowed_hosts=set())
    result=await jira.search_issues("project=OPS")
    assert result.status is IntegrationStatus.UNCONFIGURED and result.configured is False and result.error_code=="integration_unconfigured"


def test_host_allowlist_denies_nonapproved_destination():
    with pytest.raises(IntegrationHostDenied):
        ResilientReadClient(base_url="https://evil.example",allowed_hosts={"api.github.com"})

@pytest.mark.asyncio
async def test_redirect_to_nonallowlisted_host_is_denied():
    def handler(req): return httpx.Response(302,headers={"Location":"https://evil.example/steal"})
    c=ResilientReadClient(base_url="https://api.github.com",allowed_hosts={"api.github.com"},transport=httpx.MockTransport(handler))
    with pytest.raises(IntegrationHostDenied): await c.request("GET","/repos/o/r")

@pytest.mark.asyncio
async def test_request_quota_stops_pagination():
    def handler(req):
        return httpx.Response(200,json=[{"id":1}],headers={"Link":'<https://api.github.com/repos/o/r/pulls?page=2>; rel="next"'})
    gh=GitHubIntegration(base_url="https://api.github.com",token="t",transport=httpx.MockTransport(handler),policy=HTTPIntegrationPolicy(max_requests=1))
    result=await gh.list_pull_requests("o","r",max_pages=5)
    assert result.status is IntegrationStatus.FAILED and result.error_code=="integration_quota_exceeded" and result.requests_made==1

@pytest.mark.asyncio
async def test_prometheus_range_contract_uses_exact_window():
    start=datetime(2026,8,17,12,0,tzinfo=timezone.utc); end=datetime(2026,8,17,13,0,tzinfo=timezone.utc)
    def handler(req):
        assert req.url.path=="/api/v1/query_range" and req.url.params["start"]==start.isoformat() and req.url.params["end"]==end.isoformat()
        return httpx.Response(200,json={"status":"success","data":{"resultType":"matrix","result":[{"metric":{"service":"checkout"},"values":[[1723896000,"1"]]}]}})
    a=RangeIntegration(IntegrationType.PROMETHEUS,base_url="http://prometheus:9090",path="/api/v1/query_range",allowed_hosts={"prometheus"},transport=httpx.MockTransport(handler))
    r=await a.query(query='up{service="checkout"}',start=start,end=end,service="checkout",environment="production")
    assert r.status is IntegrationStatus.OK and r.records[0].data["metric"]["service"]=="checkout"

@pytest.mark.asyncio
async def test_logs_and_traces_use_bounded_time_ranges():
    start=datetime(2026,8,17,12,0,tzinfo=timezone.utc); end=datetime(2026,8,17,12,5,tzinfo=timezone.utc); seen=[]
    def handler(req): seen.append((req.url.path,dict(req.url.params))); return httpx.Response(200,json={"data":{"result":[]},"traces":[]})
    tr=RangeIntegration(IntegrationType.TRACE,base_url="http://tempo:3200",path="/api/search",allowed_hosts={"tempo"},transport=httpx.MockTransport(handler))
    lg=RangeIntegration(IntegrationType.LOG,base_url="http://loki:3100",path="/loki/api/v1/query_range",allowed_hosts={"loki"},transport=httpx.MockTransport(handler))
    await tr.query(query='{ resource.service.name = "checkout" }',start=start,end=end,limit=50)
    await lg.query(query='{service="checkout"}',start=start,end=end,limit=50)
    assert seen[0][1]["start"]==str(int(start.timestamp())) and seen[0][1]["end"]==str(int(end.timestamp()))
    assert seen[1][1]["start"]==str(int(start.timestamp()*1e9)) and seen[1][1]["end"]==str(int(end.timestamp()*1e9))

@pytest.mark.asyncio
async def test_synthetic_bundle_has_live_contract_shape_and_is_deterministic():
    start=datetime(2026,8,17,12,0,tzinfo=timezone.utc); end=datetime(2026,8,17,13,0,tzinfo=timezone.utc)
    s=SyntheticIntegrationBundle(); a=await s.snapshot(service="checkout",environment="production",start=start,end=end); b=await s.snapshot(service="checkout",environment="production",start=start,end=end)
    assert set(a)==set(x.value for x in IntegrationType) and a==b
    assert all(v.status is IntegrationStatus.OK for v in a.values())

@pytest.mark.asyncio
async def test_auth_failure_is_not_retried():
    calls=0
    def handler(req):
        nonlocal calls; calls+=1
        return httpx.Response(401,json={"message":"bad token"})
    c=ResilientReadClient(base_url="https://api.github.com",allowed_hosts={"api.github.com"},transport=httpx.MockTransport(handler),policy=HTTPIntegrationPolicy(max_attempts=3,backoff_base_seconds=0))
    from verideploy.integrations.errors import IntegrationRequestFailed
    with pytest.raises(IntegrationRequestFailed): await c.request("GET","/user")
    assert calls==1

@pytest.mark.asyncio
async def test_provider_retry_hint_above_policy_bound_fails_instead_of_retrying_early():
    calls=0
    def handler(req):
        nonlocal calls; calls+=1
        return httpx.Response(429,headers={"Retry-After":"120"},json={})
    c=ResilientReadClient(base_url="https://api.github.com",allowed_hosts={"api.github.com"},transport=httpx.MockTransport(handler),policy=HTTPIntegrationPolicy(max_attempts=3,max_retry_delay_seconds=1,backoff_base_seconds=0))
    from verideploy.integrations.errors import IntegrationRequestFailed
    with pytest.raises(IntegrationRequestFailed): await c.request("GET","/user")
    assert calls==1

@pytest.mark.asyncio
async def test_jira_basic_auth_header_uses_email_and_api_token_without_leaking_secret():
    import base64
    seen={}
    def handler(req):
        seen['auth']=req.headers.get('authorization')
        return httpx.Response(200,json={'issues':[],'isLast':True})
    jira=JiraIntegration(base_url='https://acme.atlassian.net',token='jira-secret',email='ops@example.com',auth_mode='basic',allowed_hosts={'acme.atlassian.net'},transport=httpx.MockTransport(handler))
    result=await jira.search_issues('project=OPS')
    expected='Basic '+base64.b64encode(b'ops@example.com:jira-secret').decode()
    assert seen['auth']==expected and 'jira-secret' not in result.model_dump_json()

@pytest.mark.asyncio
async def test_jira_bearer_auth_supported_for_oauth_gateway():
    def handler(req):
        assert req.headers.get('authorization')=='Bearer oauth-token'
        return httpx.Response(200,json={'issues':[],'isLast':True})
    jira=JiraIntegration(base_url='https://api.atlassian.com/ex/jira/cloud-id',token='oauth-token',auth_mode='bearer',allowed_hosts={'api.atlassian.com'},transport=httpx.MockTransport(handler))
    result=await jira.search_issues('project=OPS')
    assert result.status is IntegrationStatus.OK

@pytest.mark.asyncio
async def test_grafana_annotation_response_is_normalized_to_records():
    start=datetime(2026,8,17,12,0,tzinfo=timezone.utc); end=datetime(2026,8,17,13,0,tzinfo=timezone.utc)
    def handler(req):
        return httpx.Response(200,json=[{'id':12,'time':int(start.timestamp()*1000),'text':'deploy checkout'}])
    a=RangeIntegration(IntegrationType.GRAFANA,base_url='http://grafana:3000',path='/api/annotations',allowed_hosts={'grafana'},transport=httpx.MockTransport(handler))
    result=await a.query(query='',start=start,end=end,service='checkout',environment='production')
    assert result.records[0].source_id=='12' and result.records[0].observed_at==start

@pytest.mark.asyncio
async def test_tempo_trace_response_is_normalized_to_stable_trace_record():
    start=datetime(2026,8,17,12,0,tzinfo=timezone.utc); end=datetime(2026,8,17,13,0,tzinfo=timezone.utc)
    ns=int(start.timestamp()*1e9)
    def handler(req):
        return httpx.Response(200,json={'traces':[{'traceID':'abc123','startTimeUnixNano':str(ns),'rootServiceName':'checkout'}]})
    a=RangeIntegration(IntegrationType.TRACE,base_url='http://tempo:3200',path='/api/search',allowed_hosts={'tempo'},transport=httpx.MockTransport(handler))
    result=await a.query(query='{ resource.service.name = "checkout" }',start=start,end=end)
    assert result.records[0].source_id=='abc123' and result.records[0].observed_at==start

@pytest.mark.asyncio
async def test_loki_log_response_normalizes_each_line_with_stable_id():
    start=datetime(2026,8,17,12,0,tzinfo=timezone.utc); end=datetime(2026,8,17,13,0,tzinfo=timezone.utc)
    ns=str(int(start.timestamp()*1e9))
    payload={'data':{'result':[{'stream':{'service':'checkout','environment':'production'},'values':[[ns,'error one'],[str(int(ns)+1),'error two']]}]}}
    def handler(req): return httpx.Response(200,json=payload)
    a=RangeIntegration(IntegrationType.LOG,base_url='http://loki:3100',path='/loki/api/v1/query_range',allowed_hosts={'loki'},transport=httpx.MockTransport(handler))
    first=await a.query(query='{service="checkout"}',start=start,end=end)
    second=await a.query(query='{service="checkout"}',start=start,end=end)
    assert len(first.records)==2 and first.records[0].source_id==second.records[0].source_id and first.records[0].data['line']=='error one'
