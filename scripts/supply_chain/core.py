from __future__ import annotations
import hashlib, json, os, subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT=Path(__file__).resolve().parents[2]

def sha256_file(path: Path)->str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()

def load_json(path: str|Path)->dict[str,Any]:
    return json.loads((ROOT/Path(path)).read_text())

def git_commit()->str:
    env=os.getenv('GITHUB_SHA') or os.getenv('CI_COMMIT_SHA')
    if env: return env
    try:return subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True,stderr=subprocess.DEVNULL).strip()
    except Exception:return 'UNAVAILABLE_OFFLINE_ARCHIVE'

def provenance()->dict[str,str]:
    return {
      'git_commit':git_commit(), 'ci_provider':os.getenv('CI_PROVIDER','github-actions' if os.getenv('GITHUB_ACTIONS') else 'offline-validation'),
      'ci_run_id':os.getenv('GITHUB_RUN_ID') or os.getenv('CI_RUN_ID','offline'),
      'workflow':os.getenv('GITHUB_WORKFLOW') or os.getenv('CI_WORKFLOW','offline-validation'),
      'source_repository':os.getenv('GITHUB_REPOSITORY') or os.getenv('CI_REPOSITORY','verideploy-ai')}

def dependency_snapshot()->dict[str,Any]:
    pkg=load_json('package.json')
    py=(ROOT/'pyproject.toml').read_text()
    deps=[]; inside=False
    for line in py.splitlines():
        if line.strip()=='dependencies = [': inside=True; continue
        if inside and line.strip()==']': break
        if inside and line.strip().startswith('"'): deps.append(line.strip().strip(',').strip('"'))
    return {'node':pkg.get('devDependencies',{}),'python_direct_requirements':deps,'note':'Direct-dependency snapshot only; release still requires pnpm-lock.yaml and uv.lock.'}

def build_artifact_manifest(paths:list[str])->dict[str,Any]:
    items=[]
    for raw in paths:
        p=ROOT/raw
        if p.exists() and p.is_file(): items.append({'path':raw,'sha256':sha256_file(p),'size_bytes':p.stat().st_size})
    return {'schema_version':1,'release_version':load_json('config/release/version.json')['version'],'provenance':provenance(),'artifacts':items}

def validate_exception(exc:dict[str,Any])->list[str]:
    required={'id','kind','subject','reason','owner','ticket','expires_at'}
    return sorted(required-set(exc))

def release_gate(*,require_network_material:bool=True)->dict[str,Any]:
    policy=load_json('config/supply-chain/policy.json'); exceptions=load_json('config/supply-chain/exceptions.json')['exceptions']
    findings=[]
    for e in exceptions:
        missing=validate_exception(e)
        if missing: findings.append({'severity':'HIGH','control':'SC-EXCEPTION','detail':f"{e.get('id','unknown')} missing {missing}"})
    locks={'pnpm-lock.yaml':(ROOT/'pnpm-lock.yaml').exists(),'uv.lock':(ROOT/'uv.lock').exists()}
    images=load_json('config/supply-chain/base-images.json')['images']
    digests=all(bool(i.get('digest')) for i in images)
    if require_network_material:
        for name,ok in locks.items():
            if not ok: findings.append({'severity':'HIGH','control':'SC-LOCK','detail':f'{name} missing'})
        if not digests: findings.append({'severity':'HIGH','control':'SC-IMAGE-DIGEST','detail':'one or more base image digests are not pinned'})
    return {'passed':not any(f['severity'] in {'HIGH','CRITICAL'} for f in findings),'locks':locks,'base_images_digest_pinned':digests,'findings':findings,'policy_version':policy['release_version']}
