from __future__ import annotations
import json,re
from pathlib import Path
from scripts.supply_chain.core import ROOT, dependency_snapshot

def node_components():
    pkg=json.loads((ROOT/'package.json').read_text()); out=[]
    for scope in ('dependencies','devDependencies'):
        for name,ver in sorted(pkg.get(scope,{}).items()): out.append((name,ver,'npm'))
    for pkgfile in sorted((ROOT/'apps').glob('*/package.json')):
        d=json.loads(pkgfile.read_text())
        for scope in ('dependencies','devDependencies'):
            for name,ver in sorted(d.get(scope,{}).items()): out.append((name,ver,'npm'))
    return sorted(set(out))

def python_components():
    out=[]
    for spec in dependency_snapshot()['python_direct_requirements']:
        name=re.split(r'[<>=!~\[]', spec, maxsplit=1)[0]
        out.append((name,spec,'pypi'))
    return out

def main():
    components=node_components()+python_components()
    cdx={'bomFormat':'CycloneDX','specVersion':'1.6','version':1,'metadata':{'component':{'type':'application','name':'verideploy-ai','version':'0.68.0'},'properties':[{'name':'verideploy:scope','value':'direct-dependencies-offline'}]},'components':[{'type':'library','name':n,'version':v,'purl':f'pkg:{eco}/{n}@{v}' if eco=='npm' and not v.startswith('workspace:') else None} for n,v,eco in components]}
    for c in cdx['components']:
        if c['purl'] is None: c.pop('purl')
    spdx={'spdxVersion':'SPDX-2.3','dataLicense':'CC0-1.0','SPDXID':'SPDXRef-DOCUMENT','name':'verideploy-ai-direct-dependencies','documentNamespace':'https://verideploy.example/sbom/0.68.0/offline','creationInfo':{'creators':['Tool: VeriDeploy offline SBOM generator'],'created':'2026-08-19T00:00:00Z','comment':'Direct dependency inventory only; trusted release CI must regenerate a complete transitive SBOM from locked dependencies and built images.'},'packages':[{'name':n,'SPDXID':f'SPDXRef-Package-{i}','versionInfo':v,'downloadLocation':'NOASSERTION','filesAnalyzed':False,'licenseConcluded':'NOASSERTION','licenseDeclared':'NOASSERTION'} for i,(n,v,_) in enumerate(components,1)]}
    out=ROOT/'artifacts/supply-chain'; out.mkdir(parents=True,exist_ok=True)
    (out/'sbom.cyclonedx.json').write_text(json.dumps(cdx,indent=2)+'\n')
    (out/'sbom.spdx.json').write_text(json.dumps(spdx,indent=2)+'\n')
    return 0
if __name__=='__main__': raise SystemExit(main())
