#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, subprocess
from pathlib import Path

GROUPS={
 "web": ("apps/web/","packages/","contracts/","package.json","pnpm-workspace.yaml","turbo.json"),
 "gateway": ("apps/gateway/","packages/","contracts/","package.json","pnpm-workspace.yaml","turbo.json"),
 "python": ("src/","services/","workers/","tests/","pyproject.toml","uv.lock","config/"),
 "contracts": ("contracts/","scripts/validate_contracts.py"),
 "kubernetes": ("infrastructure/helm/","infrastructure/kubernetes/","scripts/deploy/"),
}
GLOBAL=(".github/","config/monorepo/","config/release/","scripts/validate_monorepo.py")

def changes(base:str, head:str)->list[str]:
    out=subprocess.check_output(["git","diff","--name-only",f"{base}...{head}"],text=True)
    return [x for x in out.splitlines() if x]

def compute(paths:list[str])->dict[str,bool]:
    global_hit=any(any(p.startswith(g) or p==g for g in GLOBAL) for p in paths)
    return {name: global_hit or any(any(p.startswith(prefix) or p==prefix for prefix in prefixes) for p in paths) for name,prefixes in GROUPS.items()}

def main()->int:
    ap=argparse.ArgumentParser(); ap.add_argument("--base"); ap.add_argument("--head",default="HEAD"); ap.add_argument("paths",nargs="*")
    a=ap.parse_args(); paths=a.paths if a.paths else changes(a.base or "HEAD~1",a.head)
    print(json.dumps({"changed":paths,"affected":compute(paths)},sort_keys=True))
    return 0
if __name__=="__main__": raise SystemExit(main())
