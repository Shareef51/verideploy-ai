from __future__ import annotations
from datetime import datetime, timezone
import base64, hashlib, json
from typing import Any
from urllib.parse import urlparse
import httpx
from .contracts import IntegrationRecord, IntegrationResult, IntegrationStatus, IntegrationType
from .errors import IntegrationError, IntegrationUnconfigured
from .http import HTTPIntegrationPolicy, ResilientReadClient

def _host(url:str|None)->set[str]:
    if not url: return set()
    h=urlparse(url).hostname
    return {h} if h else set()

def _unconfigured(source:IntegrationType)->IntegrationResult:
    return IntegrationResult(source=source,status=IntegrationStatus.UNCONFIGURED,configured=False,error_code="integration_unconfigured")

class GitHubIntegration:
    def __init__(self, *, base_url:str|None, token:str|None, allowed_hosts:set[str]|None=None, transport=None, policy=None):
        headers={"Accept":"application/vnd.github+json","X-GitHub-Api-Version":"2022-11-28"}
        if token: headers["Authorization"]=f"Bearer {token}"
        self.client=ResilientReadClient(base_url=base_url,allowed_hosts=allowed_hosts or _host(base_url),headers=headers,transport=transport,policy=policy)
    async def repository_get(self, owner:str, repo:str)->dict[str,Any]:
        if not self.client.configured: raise IntegrationUnconfigured("GitHub integration is not configured")
        budget=self.client.new_budget(); r=await self.client.request("GET",f"/repos/{owner}/{repo}",budget=budget)
        data=r.json(); return data if isinstance(data,dict) else {"items":data}
    async def pull_request_get(self, owner:str, repo:str, number:int)->dict[str,Any]:
        if not self.client.configured: raise IntegrationUnconfigured("GitHub integration is not configured")
        budget=self.client.new_budget(); r=await self.client.request("GET",f"/repos/{owner}/{repo}/pulls/{number}",budget=budget)
        data=r.json(); return data if isinstance(data,dict) else {"items":data}
    async def list_pull_requests(self, owner:str, repo:str, *, per_page:int=50, max_pages:int=5)->IntegrationResult:
        if not self.client.configured: return _unconfigured(IntegrationType.GITHUB)
        records=[]; next_url=f"/repos/{owner}/{repo}/pulls?state=all&per_page={min(max(per_page,1),100)}"; pages=0; budget=self.client.new_budget()
        try:
            while next_url and pages<max_pages:
                r=await self.client.request("GET",next_url,budget=budget); pages+=1
                for item in r.json():
                    records.append(IntegrationRecord(source=IntegrationType.GITHUB,source_id=str(item.get("id") or item.get("number")),data=item))
                next_url=_github_next(r.headers.get("link"))
            return IntegrationResult(source=IntegrationType.GITHUB,status=IntegrationStatus.OK,records=records,pages_fetched=pages,requests_made=budget.requests_made)
        except IntegrationError as exc:
            return IntegrationResult(source=IntegrationType.GITHUB,status=IntegrationStatus.FAILED,error_code=exc.code,pages_fetched=pages,requests_made=budget.requests_made)

def _github_next(link:str|None)->str|None:
    if not link: return None
    for part in link.split(","):
        if 'rel="next"' in part:
            return part[part.find("<")+1:part.find(">")]
    return None

class JiraIntegration:
    def __init__(self, *, base_url:str|None, token:str|None, email:str|None=None, auth_mode:str="basic", allowed_hosts:set[str]|None=None, transport=None, policy=None):
        headers={"Accept":"application/json"}
        if token:
            if auth_mode == "basic":
                if not email:
                    raise ValueError("Jira basic auth requires an Atlassian account email")
                encoded=base64.b64encode(f"{email}:{token}".encode()).decode()
                headers["Authorization"]=f"Basic {encoded}"
            elif auth_mode == "bearer":
                headers["Authorization"]=f"Bearer {token}"
            else:
                raise ValueError("unsupported Jira auth mode")
        self.client=ResilientReadClient(base_url=base_url,allowed_hosts=allowed_hosts or _host(base_url),headers=headers,transport=transport,policy=policy)
    async def search_issues(self,jql:str,*,max_results:int=50,max_pages:int=5)->IntegrationResult:
        if not self.client.configured: return _unconfigured(IntegrationType.JIRA)
        token=None; records=[]; pages=0; budget=self.client.new_budget()
        try:
            while pages<max_pages:
                params={"jql":jql,"maxResults":min(max(max_results,1),100)}
                if token: params["nextPageToken"]=token
                r=await self.client.request("GET","/rest/api/3/search/jql",params=params,budget=budget); pages+=1; payload=r.json()
                for item in payload.get("issues",[]): records.append(IntegrationRecord(source=IntegrationType.JIRA,source_id=str(item.get("id") or item.get("key")),data=item))
                token=payload.get("nextPageToken")
                if payload.get("isLast") is True or not token: break
            return IntegrationResult(source=IntegrationType.JIRA,status=IntegrationStatus.OK,records=records,pages_fetched=pages,requests_made=budget.requests_made)
        except IntegrationError as exc:
            return IntegrationResult(source=IntegrationType.JIRA,status=IntegrationStatus.FAILED,error_code=exc.code,pages_fetched=pages,requests_made=budget.requests_made)

class RangeIntegration:
    def __init__(self, source:IntegrationType, *, base_url:str|None, path:str, token:str|None=None, allowed_hosts:set[str]|None=None, transport=None, policy=None):
        headers={"Accept":"application/json"}
        if token: headers["Authorization"]=f"Bearer {token}"
        self.source=source; self.path=path
        self.client=ResilientReadClient(base_url=base_url,allowed_hosts=allowed_hosts or _host(base_url),headers=headers,transport=transport,policy=policy)
    async def query(self, *, query:str, start:datetime, end:datetime, limit:int=200, service:str|None=None, environment:str|None=None)->IntegrationResult:
        if not self.client.configured: return _unconfigured(self.source)
        budget=self.client.new_budget()
        try:
            if self.source is IntegrationType.PROMETHEUS:
                params={"query":query,"start":start.isoformat(),"end":end.isoformat(),"step":"15s","limit":limit}
            elif self.source is IntegrationType.LOG:
                params={"query":query,"start":str(int(start.timestamp()*1e9)),"end":str(int(end.timestamp()*1e9)),"limit":limit,"direction":"forward"}
            elif self.source is IntegrationType.TRACE:
                params={"q":query,"start":int(start.timestamp()),"end":int(end.timestamp()),"limit":limit}
            else:
                params={"from":int(start.timestamp()*1000),"to":int(end.timestamp()*1000),"limit":limit}
                if service: params["tags"]=f"service:{service}"
            r=await self.client.request("GET",self.path,params=params,budget=budget); payload=r.json()
            records=self._records(payload)
            return IntegrationResult(source=self.source,status=IntegrationStatus.OK,records=records,pages_fetched=1,requests_made=budget.requests_made)
        except IntegrationError as exc:
            return IntegrationResult(source=self.source,status=IntegrationStatus.FAILED,error_code=exc.code,requests_made=budget.requests_made)
    def _records(self,payload:Any)->list[IntegrationRecord]:
        if self.source is IntegrationType.PROMETHEUS:
            result=(payload.get("data",{}) if isinstance(payload,dict) else {}).get("result",[])
            return [IntegrationRecord(source=self.source,source_id=str(item.get("metric",{})),data={"metric":item.get("metric",{}),"values":item.get("values",[]),"value":item.get("value")}) for item in result]
        if self.source is IntegrationType.GRAFANA:
            items=payload if isinstance(payload,list) else []
            out=[]
            for item in items:
                millis=item.get("time") or item.get("timeEnd")
                observed=datetime.fromtimestamp(float(millis)/1000,tz=timezone.utc) if millis is not None else None
                out.append(IntegrationRecord(source=self.source,source_id=str(item.get("id") or item.get("uid") or millis),observed_at=observed,data=item))
            return out
        if self.source is IntegrationType.TRACE:
            items=payload.get("traces",[]) if isinstance(payload,dict) else []
            out=[]
            for item in items:
                ns=item.get("startTimeUnixNano") or item.get("startTimeUnixNanos")
                observed=datetime.fromtimestamp(int(ns)/1e9,tz=timezone.utc) if ns is not None else None
                out.append(IntegrationRecord(source=self.source,source_id=str(item.get("traceID") or item.get("traceId") or ns),observed_at=observed,data=item))
            return out
        if self.source is IntegrationType.LOG:
            streams=(payload.get("data",{}) if isinstance(payload,dict) else {}).get("result",[])
            out=[]
            for stream in streams:
                labels=stream.get("stream",{})
                for ns,line in stream.get("values",[]):
                    observed=datetime.fromtimestamp(int(ns)/1e9,tz=timezone.utc)
                    out.append(IntegrationRecord(source=self.source,source_id=hashlib.sha256(json.dumps({"ts":str(ns),"labels":labels},sort_keys=True,separators=(",",":"),default=str).encode()).hexdigest()[:24],observed_at=observed,data={"labels":labels,"line":str(line)}))
            return out
        return []

class SyntheticIntegrationBundle:
    async def snapshot(self, *, service:str, environment:str, start:datetime, end:datetime)->dict[str,IntegrationResult]:
        out={}
        for source in IntegrationType:
            out[source.value]=IntegrationResult(source=source,status=IntegrationStatus.OK,records=[IntegrationRecord(source=source,source_id=f"synthetic:{source.value}:{service}:{environment}",observed_at=start,data={"service":service,"environment":environment,"start":start.isoformat(),"end":end.isoformat()})],pages_fetched=1,requests_made=0)
        return out
