from __future__ import annotations
import json,re
from pathlib import Path
from typing import Any

RELEASE="0.86.0"

def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))

def validate_final_release(root: Path) -> dict[str, Any]:
    cfg=_json(root/"config/release/final-release.json")
    findings: list[str]=[]
    release_meta=_json(root/"config/release/version.json")
    if release_meta != {"version": RELEASE}: findings.append("release metadata drift")
    pkg=_json(root/"package.json")
    if pkg.get("version") != RELEASE: findings.append("root package version drift")
    chart=(root/"infrastructure/helm/verideploy/Chart.yaml").read_text()
    if f"version: {RELEASE}" not in chart or f"appVersion: {RELEASE}" not in chart: findings.append("Helm chart version drift")
    values=(root/"infrastructure/helm/verideploy/values-production.yaml").read_text()
    if values.count(f'tag: "{RELEASE}"') < 4 or f'imageTag: "{RELEASE}"' not in values: findings.append("production image tags are not aligned")
    topology=_json(root/"config/architecture/production-topology.json")
    if topology.get("release") != RELEASE: findings.append("production topology release drift")
    if len(cfg.get("images",[])) != 4: findings.append("four versioned release images are required")
    for image in cfg.get("images",[]):
        if not image.get("ref","").endswith(f":{RELEASE}"): findings.append(f"unversioned image: {image.get('component')}")
        p=root/image.get("dockerfile","")
        if not p.exists() or p.stat().st_size < 100: findings.append(f"missing Dockerfile: {image.get('component')}")
    for rel in cfg.get("required_artifacts",[]):
        p=root/rel
        if not p.exists() or p.stat().st_size == 0: findings.append(f"missing release artifact: {rel}")
    tfdir=root/"infrastructure/terraform"
    tf_files=list(tfdir.glob("*.tf"))
    if len(tf_files) < 4: findings.append("Terraform baseline incomplete")
    tf_text="\n".join(p.read_text() for p in tf_files)
    for token in ("helm_release", "kubernetes_namespace_v1", "external_secret_store_name", "release_version"):
        if token not in tf_text: findings.append(f"Terraform missing {token}")
    workflow=(root/".github/workflows/release.yml").read_text()
    required_workflow=["docker buildx build","--provenance=true","--sbom=true","cosign sign --yes","cosign verify","helm package","terraform plan","cosign sign-blob"]
    for token in required_workflow:
        if token not in workflow: findings.append(f"release workflow missing: {token}")
    if "|| true" in workflow: findings.append("release workflow contains fail-open command")
    rollback=(root/"scripts/release/rollback.sh").read_text()
    deploy=(root/"scripts/release/deploy.sh").read_text()
    if "VERIDEPLOY_ROLLBACK_APPROVED" not in rollback: findings.append("rollback lacks explicit human approval")
    if "VERIDEPLOY_RELEASE_APPROVED" not in deploy: findings.append("production apply lacks explicit human approval")
    seed=(root/"scripts/release/seed_demo.sh").read_text()
    if "/api/v1/demos/multimodal-killer/run" not in seed or "INSERT INTO" in seed.upper(): findings.append("demo seed path must use public API")
    readme=(root/"README.md").read_text()
    if "Production Release and Handoff" not in readme or RELEASE not in readme: findings.append("README missing final handoff section")
    # Secrets must be placeholders / references only in checked-in deployment assets.
    sensitive_scan="\n".join((root/p).read_text(errors="ignore") for p in ["infrastructure/terraform/terraform.tfvars.example","config/release/final-release.json"])
    forbidden=[r"sk-[A-Za-z0-9_-]{20,}", r"AKIA[0-9A-Z]{16}", r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"]
    if any(re.search(pattern,sensitive_scan) for pattern in forbidden): findings.append("release assets contain credential-like material")
    local=cfg.get("execution_truth",{})
    if any(local.get(k) is True for k in ("local_registry_push","local_cosign_signature","live_terraform_apply","live_restore_drill")):
        findings.append("local execution truth overclaims external release operations")
    return {
        "release":RELEASE,
        "gate":"pass" if not findings else "fail",
        "versioned_images":len(cfg.get("images",[])),
        "terraform_files":len(tf_files),
        "required_artifacts":len(cfg.get("required_artifacts",[])),
        "trusted_external_steps":["registry push","keyless cosign signing","terraform apply","kubernetes rollout","live restore drill"],
        "production_promotion_requires_external_evidence":True,
        "findings":findings,
    }
