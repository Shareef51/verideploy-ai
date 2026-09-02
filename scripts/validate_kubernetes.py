from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

import yaml

from verideploy.platform.kubernetes import simulate_single_pod_failure, simulate_single_zone_failure

ROOT = Path(__file__).resolve().parents[1]
CHART = ROOT / "infrastructure/helm/verideploy"


def _load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text())
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML object")
    return data


def _template(name: str) -> str:
    return (CHART / "templates" / name).read_text()


def validate() -> dict[str, Any]:
    chart = _load_yaml(CHART / "Chart.yaml")
    values = _load_yaml(CHART / "values.yaml")
    production = _load_yaml(CHART / "values-production.yaml")
    findings: list[str] = []

    if chart.get("apiVersion") != "v2": findings.append("chart must use Helm apiVersion v2")
    release = json.loads((ROOT / "config/release/version.json").read_text())["version"]
    if chart.get("version") != release: findings.append(f"chart version must match release version {release}")

    expected = {"web", "gateway", "ai-service", "worker"}
    workloads = values.get("workloads", {})
    if set(workloads) != expected: findings.append("workload set is incomplete")
    for name, cfg in workloads.items():
        if int(cfg.get("replicas", 0)) < 3: findings.append(f"{name}: replicas must be >= 3")
        resources = cfg.get("resources", {})
        if not resources.get("requests") or not resources.get("limits"): findings.append(f"{name}: resources missing")
        hpa = cfg.get("hpa", {})
        if not hpa.get("enabled") or int(hpa.get("minReplicas", 0)) < 3 or int(hpa.get("maxReplicas", 0)) <= int(hpa.get("minReplicas", 0)):
            findings.append(f"{name}: invalid HPA")
        pdb = cfg.get("pdb", {})
        if int(pdb.get("minAvailable", 0)) < 2: findings.append(f"{name}: PDB minAvailable must be >= 2")
        if name != "worker" and not cfg.get("probes"): findings.append(f"{name}: probes missing")

    for image, cfg in production.get("images", {}).items():
        if str(cfg.get("tag", "")).lower() in {"", "latest"}: findings.append(f"{image}: production image tag must be pinned")

    deps = values.get("dependencies", {})
    for name in ("postgres", "redis", "kafka", "objectStore"):
        if not deps.get(name, {}).get("host") or not deps.get(name, {}).get("port"):
            findings.append(f"dependency {name} missing host/port")

    workloads_tpl = _template("workloads.yaml")
    for token in ("startupProbe:", "readinessProbe:", "livenessProbe:", "topologySpreadConstraints:", "podAntiAffinity:", "maxUnavailable: 0", "readOnlyRootFilesystem: true"):
        if token not in workloads_tpl: findings.append(f"workloads template missing {token}")

    autoscaling_tpl = _template("autoscaling.yaml")
    for token in ("autoscaling/v2", "HorizontalPodAutoscaler", "stabilizationWindowSeconds: 300"):
        if token not in autoscaling_tpl: findings.append(f"HPA template missing {token}")

    pdb_tpl = _template("pdb.yaml")
    if "PodDisruptionBudget" not in pdb_tpl: findings.append("PDB template missing")

    migration_tpl = _template("migration-job.yaml")
    for token in ("pre-install,pre-upgrade", "alembic", "upgrade", "head", "activeDeadlineSeconds"):
        if token not in migration_tpl: findings.append(f"migration job missing {token}")

    network_tpl = _template("networkpolicy.yaml")
    for token in (
        "verideploy-default-deny",
        "verideploy-web-egress",
        "verideploy-gateway-ingress",
        "verideploy-gateway-egress",
        "verideploy-ai-ingress",
        "verideploy-ai-worker-egress",
        "kube-system",
    ):
        if token not in network_tpl: findings.append(f"network policy missing {token}")

    drill = ROOT / "scripts/deploy/pod_failure_drill.sh"
    if not drill.exists() or "kubectl" not in drill.read_text(): findings.append("live pod-failure drill script missing")

    canary_tpl = _template("canary.yaml")
    for token in ("verideploy-gateway-canary", "verideploy.ai/track: canary", "max-traffic-percent"):
        if token not in canary_tpl: findings.append(f"canary template missing {token}")

    pod = simulate_single_pod_failure(values)
    zone = simulate_single_zone_failure(values, zones=3)
    if not pod.passed: findings.append("single pod failure drill failed")
    if not zone.passed: findings.append("single zone failure drill failed")

    result = {
        "chart_version": chart.get("version"),
        "workloads": sorted(workloads),
        "single_pod_failure": {"passed": pod.passed, "workloads": dict(pod.workload_results)},
        "single_zone_failure": {"passed": zone.passed, "workloads": dict(zone.workload_results)},
        "validation_mode": "offline-static-and-failure-simulation",
        "helm_cli_available_locally": bool(shutil.which("helm")),
        "kubectl_available_locally": bool(shutil.which("kubectl")),
        "canary_enabled_by_default": bool(values.get("canary", {}).get("enabled")),
        "production_images_pinned": all(str(v.get("tag", "")).lower() not in {"", "latest"} for v in production.get("images", {}).values()),
        "findings": findings,
        "passed": not findings,
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", default=str(ROOT / "evals/reports/kubernetes-resilience.json"))
    args = parser.parse_args()
    report = validate()
    out = Path(args.report); out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
