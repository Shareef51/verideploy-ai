from __future__ import annotations
from uuid import UUID
from .schemas import RetrievalAuthorizationScope, parse_csv_header

def authorization_from_headers(*,tenant_id:UUID,permissions:str|None=None,allowed_services:str|None=None,allowed_environments:str|None=None,allowed_teams:str|None=None,allowed_document_kinds:str|None=None,default_permissions:frozenset[str]=frozenset({"retrieval.read"}))->RetrievalAuthorizationScope:
    perms=parse_csv_header(permissions) or default_permissions
    return RetrievalAuthorizationScope(tenant_id=tenant_id,permissions=perms,allowed_services=parse_csv_header(allowed_services),allowed_environments=parse_csv_header(allowed_environments),allowed_teams=parse_csv_header(allowed_teams),allowed_document_kinds=parse_csv_header(allowed_document_kinds))
