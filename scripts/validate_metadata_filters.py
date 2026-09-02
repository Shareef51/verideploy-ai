from __future__ import annotations
import json
from itertools import combinations
from pathlib import Path
from uuid import UUID
from verideploy.rag.access.schemas import RequestedMetadataFilters, RetrievalAuthorizationScope, build_effective_scope, READ_PERMISSION
TENANT=UUID('00000000-0000-4000-8000-000000000035')
UNIVERSE=('checkout','payments','ledger')
def subsets():
    return [frozenset(c) for r in range(len(UNIVERSE)+1) for c in combinations(UNIVERSE,r)]
def main():
    checked=0; violations=[]
    for trusted in subsets():
        for requested in subsets():
            auth=RetrievalAuthorizationScope(tenant_id=TENANT,permissions=frozenset({READ_PERMISSION}),allowed_services=trusted)
            scope=build_effective_scope(authorization=auth,requested=RequestedMetadataFilters(services=list(requested)))
            checked+=1
            if scope.services is None or not set(scope.services).issubset(set(trusted)):
                violations.append({'trusted':sorted(trusted),'requested':sorted(requested),'effective':sorted(scope.services or [])})
            if requested and not (trusted & requested) and not scope.empty:
                violations.append({'trusted':sorted(trusted),'requested':sorted(requested),'reason':'disjoint scope was not empty'})
    result={'valid':not violations,'cases_checked':checked,'violations':violations,'property':'effective scope never widens trusted service scope'}
    out=Path('artifacts/metadata-filter-validation.json'); out.parent.mkdir(exist_ok=True); out.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
    print(json.dumps(result,sort_keys=True))
    if violations: raise SystemExit(1)
if __name__=='__main__': main()
