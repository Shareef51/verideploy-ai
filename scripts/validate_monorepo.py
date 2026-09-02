#!/usr/bin/env python3
from __future__ import annotations
import hashlib, json, re, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
POLICY=json.loads((ROOT/'config/monorepo/policy.json').read_text())
VERSION=POLICY['release_version']

def sha(path:Path)->str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def package_version(path:Path)->str:
    return json.loads(path.read_text())['version']

def python_version()->str:
    m=re.search(r'(?m)^version = "([^"]+)"',(ROOT/'pyproject.toml').read_text()); return m.group(1) if m else ''

def generated_sources()->list[Path]:
    out=[]
    for raw in POLICY['generated_contract_sources']:
        p=ROOT/raw
        if p.is_file(): out.append(p)
        elif p.is_dir(): out.extend(sorted(x for x in p.rglob('*') if x.is_file()))
    return sorted(set(out))

def manifest()->dict:
    files={str(p.relative_to(ROOT)):sha(p) for p in generated_sources()}
    packages={name:{"path":cfg['path'],"version":package_version(ROOT/cfg['path']/'package.json'),"owner":cfg['owner']} for name,cfg in POLICY['workspace_packages'].items()}
    return {"schema_version":1,"release_version":VERSION,"python_version":python_version(),"packages":packages,"generated_contracts":files,"turbo_sha256":sha(ROOT/'turbo.json'),"workspace_sha256":sha(ROOT/'pnpm-workspace.yaml')}

def validate()->list[str]:
    errors=[]
    for f in POLICY['required_files']:
        if not (ROOT/f).exists(): errors.append(f"missing required file: {f}")
    for name,cfg in POLICY['workspace_packages'].items():
        p=ROOT/cfg['path']/'package.json'
        if not p.exists(): errors.append(f"missing workspace package: {name}")
        elif package_version(p)!=VERSION: errors.append(f"version drift: {name}")
    if package_version(ROOT/'package.json')!=VERSION: errors.append('root package version drift')
    if python_version()!=VERSION: errors.append('python project version drift')
    turbo=json.loads((ROOT/'turbo.json').read_text())
    for task in POLICY['build_tasks']:
        if task not in turbo.get('tasks',{}): errors.append(f"missing turbo task: {task}")
    co=(ROOT/'.github/CODEOWNERS').read_text() if (ROOT/'.github/CODEOWNERS').exists() else ''
    for cfg in POLICY['workspace_packages'].values():
        if cfg['owner'] not in co: errors.append(f"owner not represented in CODEOWNERS: {cfg['owner']}")
    expected=manifest(); ip=ROOT/'config/monorepo/integrity.json'
    if ip.exists() and json.loads(ip.read_text())!=expected: errors.append('integrity manifest is stale')
    return errors

def main()->int:
    if '--write' in sys.argv:
        out=manifest(); (ROOT/'config/monorepo/integrity.json').write_text(json.dumps(out,indent=2,sort_keys=True)+'\n')
    errors=validate(); report={"version":VERSION,"passed":not errors,"errors":errors,"integrity":manifest()}
    rp=ROOT/'evals/reports/monorepo-hardening.json'; rp.parent.mkdir(parents=True,exist_ok=True); rp.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    print(json.dumps({"passed":not errors,"errors":errors}))
    return 0 if not errors else 1
if __name__=='__main__': raise SystemExit(main())
