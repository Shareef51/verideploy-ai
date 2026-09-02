from __future__ import annotations
import csv, hashlib, io, json
from fastapi import APIRouter, Header, HTTPException, Query, Response
from verideploy.audit.core import AuditSearchQuery, AuditResult
from verideploy.audit.repository import SqlAuditRepository
from verideploy.config import get_settings

router=APIRouter(prefix='/internal/v1/audit',tags=['audit'])

def _repo(): return SqlAuditRepository(get_settings().database_url)
def _roles(raw:str)->tuple[str,...]: return tuple(x.strip() for x in raw.split(',') if x.strip())
def _authorized(roles:tuple[str,...], export:bool=False):
    allowed={'security_admin','auditor'} if export else {'viewer','developer','reviewer','security_admin','auditor'}
    if not set(roles)&allowed: raise HTTPException(status_code=403,detail='audit access denied')

@router.get('/events')
def search_events(
    x_tenant_id:str=Header(alias='x-tenant-id'), x_user_id:str=Header(alias='x-user-id'), x_auth_roles:str=Header(alias='x-auth-roles'),
    actor_id:str|None=None,action:str|None=None,resource_type:str|None=None,resource_id:str|None=None,result:str|None=None,correlation_id:str|None=None,limit:int=Query(200,ge=1,le=1000)):
    roles=_roles(x_auth_roles); _authorized(roles)
    parsed=AuditResult(result) if result else None
    rows=_repo().search(AuditSearchQuery(tenant_id=x_tenant_id,requester_id=x_user_id,requester_roles=roles,actor_id=actor_id,action=action,resource_type=resource_type,resource_id=resource_id,result=parsed,correlation_id=correlation_id,limit=limit))
    for row in rows:
        for k,v in list(row.items()):
            if hasattr(v,'isoformat'): row[k]=v.isoformat()
            elif not isinstance(v,(str,int,float,bool,type(None),dict,list)): row[k]=str(v)
    return {'events':rows,'count':len(rows)}

@router.get('/export')
def export_events(
    format:str=Query('jsonl',pattern='^(jsonl|csv)$'),x_tenant_id:str=Header(alias='x-tenant-id'),x_user_id:str=Header(alias='x-user-id'),x_auth_roles:str=Header(alias='x-auth-roles'),limit:int=Query(1000,ge=1,le=1000)):
    roles=_roles(x_auth_roles); _authorized(roles,True)
    rows=_repo().search(AuditSearchQuery(tenant_id=x_tenant_id,requester_id=x_user_id,requester_roles=roles,limit=limit))
    serial=[]
    for row in rows:
        serial.append({k:(v.isoformat() if hasattr(v,'isoformat') else str(v) if not isinstance(v,(str,int,float,bool,type(None),dict,list)) else v) for k,v in row.items()})
    if format=='jsonl': content='\n'.join(json.dumps(r,sort_keys=True,default=str) for r in serial); media='application/x-ndjson'
    else:
        out=io.StringIO(); fields=['audit_id','occurred_at','actor_type','actor_id','action','result','resource_type','resource_id','correlation_id','trace_id','event_hash']; w=csv.DictWriter(out,fieldnames=fields);w.writeheader();[w.writerow({f:r.get(f) for f in fields}) for r in serial];content=out.getvalue();media='text/csv'
    digest=hashlib.sha256(content.encode()).hexdigest()
    return Response(content,media_type=media,headers={'x-audit-export-sha256':digest,'content-disposition':f'attachment; filename="verideploy-audit.{format}"'})
