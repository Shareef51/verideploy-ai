from __future__ import annotations
import json
from pathlib import Path

def validate_architecture(root: Path) -> dict:
    policy=json.loads((root/"config/architecture/scope-integrity.json").read_text())
    errors=[]
    for item in policy["components"]:
        if not (root/item["path"]).exists(): errors.append(f"missing component: {item['path']}")
        if not (root/"docs/decisions"/item["adr"]).exists(): errors.append(f"missing ADR: {item['adr']}")
    for rel in policy["forbidden_runtime_paths"]:
        if (root/rel).exists(): errors.append(f"forbidden runtime path: {rel}")
    runtime_roots=[root/p for p in ("apps","services","workers","src") if (root/p).exists()]
    for base in runtime_roots:
        for path in base.rglob("*"):
            if not path.is_file() or path.suffix not in {".py",".ts",".tsx"}: continue
            text=path.read_text(errors="ignore")
            for pattern in policy["forbidden_runtime_patterns"]:
                if pattern in text: errors.append(f"forbidden runtime pattern {pattern}: {path.relative_to(root)}")
    # public boundary invariant
    web_offenders=[]
    for path in (root/"apps/web").rglob("*.tsx"):
        text=path.read_text(errors="ignore")
        if "AI_SERVICE_BASE_URL" in text or "/internal/v1/" in text: web_offenders.append(str(path.relative_to(root)))
    if web_offenders: errors.append("web bypasses gateway: "+",".join(web_offenders))
    # consequential action policy must remain fail closed
    if not all(policy["allowed_write_policy"].values()): errors.append("write-safety policy weakened")
    return {"valid":not errors,"errors":errors,"component_count":len(policy["components"]),"release":policy["release"]}
