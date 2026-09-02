from __future__ import annotations

import hashlib, json
from datetime import datetime, timezone
from typing import Iterable
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

READ_PERMISSION="retrieval.read"
VISUAL_PERMISSION="retrieval.visual.read"
PREVIEW_PERMISSION="retrieval.preview.read"

class RequestedMetadataFilters(BaseModel):
    model_config=ConfigDict(extra="forbid")
    services: list[str]=Field(default_factory=list,max_length=32)
    environments: list[str]=Field(default_factory=list,max_length=16)
    document_kinds: list[str]=Field(default_factory=list,max_length=16)
    severities: list[str]=Field(default_factory=list,max_length=8)
    teams: list[str]=Field(default_factory=list,max_length=32)
    occurred_from: datetime|None=None
    occurred_to: datetime|None=None

    @field_validator("services","environments","severities","teams")
    @classmethod
    def norm_list(cls,v:list[str])->list[str]:
        out=[]
        for raw in v:
            x=raw.strip().casefold()
            if x and x not in out: out.append(x)
        return out

    @field_validator("occurred_from","occurred_to")
    @classmethod
    def aware(cls,v:datetime|None)->datetime|None:
        if v is None:return None
        if v.tzinfo is None or v.utcoffset() is None: raise ValueError("metadata date filters must be timezone-aware")
        return v.astimezone(timezone.utc)

    @model_validator(mode="after")
    def valid_window(self):
        if self.occurred_from and self.occurred_to and self.occurred_from>self.occurred_to:
            raise ValueError("occurred_from must be <= occurred_to")
        return self

class RetrievalAuthorizationScope(BaseModel):
    model_config=ConfigDict(extra="forbid", frozen=True)
    tenant_id: UUID
    permissions: frozenset[str]=Field(default_factory=lambda:frozenset({READ_PERMISSION}))
    allowed_services: frozenset[str]|None=None
    allowed_environments: frozenset[str]|None=None
    allowed_teams: frozenset[str]|None=None
    allowed_document_kinds: frozenset[str]|None=None

    @field_validator("permissions","allowed_services","allowed_environments","allowed_teams",mode="before")
    @classmethod
    def norm_sets(cls,v):
        if v is None:return None
        return frozenset(str(x).strip().casefold() for x in v if str(x).strip())

class EffectiveRetrievalScope(BaseModel):
    model_config=ConfigDict(extra="forbid", frozen=True)
    tenant_id: UUID
    permissions: frozenset[str]
    services: frozenset[str]|None=None
    environments: frozenset[str]|None=None
    document_kinds: frozenset[str]|None=None
    severities: frozenset[str]|None=None
    teams: frozenset[str]|None=None
    occurred_from: datetime|None=None
    occurred_to: datetime|None=None
    empty: bool=False

    def fingerprint(self)->str:
        payload=self.model_dump(mode="json")
        return hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(",",":")).encode()).hexdigest()


def _intersect(trusted: frozenset|None, requested: Iterable|None):
    req=frozenset(requested or [])
    if trusted is None: return req or None, False
    if not req: return trusted, len(trusted)==0
    result=trusted & req
    return result, len(result)==0


def build_effective_scope(*,authorization:RetrievalAuthorizationScope,requested:RequestedMetadataFilters|None=None,required_permission:str=READ_PERMISSION)->EffectiveRetrievalScope:
    requested=requested or RequestedMetadataFilters()
    services,e1=_intersect(authorization.allowed_services,requested.services)
    environments,e2=_intersect(authorization.allowed_environments,requested.environments)
    teams,e3=_intersect(authorization.allowed_teams,requested.teams)
    kinds,e4=_intersect(authorization.allowed_document_kinds,requested.document_kinds)
    severities=frozenset(requested.severities) or None
    denied=required_permission not in authorization.permissions
    return EffectiveRetrievalScope(tenant_id=authorization.tenant_id,permissions=authorization.permissions,services=services,environments=environments,document_kinds=kinds,severities=severities,teams=teams,occurred_from=requested.occurred_from,occurred_to=requested.occurred_to,empty=denied or e1 or e2 or e3 or e4)


def parse_csv_header(value:str|None)->frozenset[str]|None:
    if value is None or not value.strip(): return None
    return frozenset(x.strip().casefold() for x in value.split(",") if x.strip())
